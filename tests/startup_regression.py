#!/usr/bin/env python3
"""Focused offline regression checks for API, cron, and mgrep startup."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
API_IMAGE = "agroportal/ontologies_api@sha256:02203b385310027165bacb3ed02bfcc2a88d6ab43a58e82a7238d1cec09989e4"
CRON_IMAGE = "agroportal/ncbo_cron@sha256:dd31d516ccb0aceee0592a02b2ae9093adb65922c9bdae0adc07802a82c3fa45"
MGREP_DIGESTS = {
    "ontoportal/mgrep-ncbo": "sha256:c5499148deff2a1c548fb19247e3d60f7e1f17ebb60f1e4035c25cba56d1a5a2",
    "ontoportal/mgrep": "sha256:874cd56f605d2bc163ed00792f2febe7884a0c5d7147fbb6ec8d21e8e3743d1e",
}
MGREP_PROFILES = {
    "matportal": ("ontoportal/mgrep-ncbo", MGREP_DIGESTS["ontoportal/mgrep-ncbo"]),
    "matportal-k3s-ci": ("ontoportal/mgrep", MGREP_DIGESTS["ontoportal/mgrep"]),
}


def load_renderer() -> Any:
    spec = importlib.util.spec_from_file_location("render_compose", ROOT / "scripts/render-compose.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Compose renderer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def profile_values(renderer: Any, profile: str, *, compose: bool = False) -> dict[str, Any]:
    values = renderer.load_yaml(ROOT / "chart/ontoportal/values.yaml")
    values = renderer.deep_merge(values, renderer.load_yaml(ROOT / f"values/profiles/{profile}.yaml"))
    if compose:
        values = renderer.deep_merge(values, renderer.load_yaml(ROOT / "values/profiles/docker-compose.yaml"))
    return values


def helm_objects(value_files: list[Path], set_values: list[str] | None = None) -> list[dict[str, Any]]:
    helm = shutil.which("helm")
    check(helm is not None, "helm is required for rendered overlay regression")
    command = [helm, "template", "startup-regression", str(ROOT / "chart/ontoportal"), "-n", "matportal"]
    for value_file in value_files:
        command += ["-f", str(value_file)]
    for value in set_values or []:
        command += ["--set", value]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    check(result.returncode == 0, f"Helm render failed:\n{result.stderr}")
    return [item for item in yaml.safe_load_all(result.stdout) if isinstance(item, dict)]


def component(objects: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for item in objects:
        if item.get("kind") != "Deployment":
            continue
        if item.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component") == name:
            return item
    raise AssertionError(f"rendered {name} Deployment not found")


def container(deployment: dict[str, Any]) -> dict[str, Any]:
    return deployment["spec"]["template"]["spec"]["containers"][0]


def check_script(script: str, label: str) -> None:
    check("bundle check" in script, f"{label} must check baked dependencies")
    check("bundle install" not in script, f"{label} must not install dependencies")
    check("BUNDLE_PATH" not in script, f"{label} must not redirect Bundler")
    check("active_support/isolated_execution_state" not in script, f"{label} has redundant ActiveSupport require")


def check_mgrep_script(script: str, label: str) -> None:
    for token in [
        "command -v mgrep",
        "/srv/mgrep/dictionary.txt",
        "/srv/mgrep/dictionary/dictionary.txt",
        "wc -c",
        "cmp -s -",
        "DUMMY",
        "pgrep -x mgrep",
        "pkill -TERM -x mgrep",
    ]:
        check(token in script, f"{label} startup missing {token}")
    for token in ["/usr/local/bin/mgrep", "while true", "tail -f /dev/null"]:
        check(token not in script, f"{label} startup still contains {token}")


def static_checks() -> None:
    renderer = load_renderer()
    objects = helm_objects([
        ROOT / "values/profiles/agroportal-clean.yaml",
        ROOT / "values/profiles/production-recommended.yaml",
        ROOT / "values/cloud/aws-eks.yaml",
    ])
    for name in ["api", "cron"]:
        pod = component(objects, name)
        env_names = {entry["name"] for entry in container(pod).get("env", [])}
        check("BUNDLE_PATH" not in env_names, f"Helm {name} redirects BUNDLE_PATH")
        check("BUNDLE_APP_CONFIG" not in env_names, f"Helm {name} redirects BUNDLE_APP_CONFIG")
        check_script(container(pod)["args"][0], f"Helm {name}")

    mgrep = container(component(objects, "mgrep"))
    check_mgrep_script(mgrep["command"][2], "Helm mgrep")
    for probe in ["startupProbe", "readinessProbe", "livenessProbe"]:
        check("tcpSocket" in mgrep.get(probe, {}), f"Helm mgrep {probe} must be TCP")

    helpers = (ROOT / "chart/ontoportal/templates/_helpers.tpl").read_text(encoding="utf-8")
    check("active_support/isolated_execution_state" not in helpers, "Helm runtime config still requires isolated execution state")

    for profile in ["ontoportal-clean", "agroportal-clean", "matportal"]:
        values = profile_values(renderer, profile, compose=True)
        check(not values["mgrep"].get("command"), f"Compose {profile} must use default mgrep supervision")
        compose = renderer.render(values)
        service = compose["services"]["mgrep"]
        check(service.get("entrypoint") == [], f"Compose {profile} must clear the image entrypoint")
        check(service["command"][:2] == ["sh", "-lc"], f"Compose {profile} mgrep must run through a shell")
        check_mgrep_script(service["command"][2], f"Compose {profile} mgrep")

        for name in ["api", "cron"]:
            service = compose["services"][name]
            check("BUNDLE_PATH" not in service.get("environment", {}), f"Compose {profile} {name} redirects BUNDLE_PATH")
            check_script(service["command"][2], f"Compose {profile} {name}")

    for profile in ["matportal", "matportal-k3s-ci"]:
        values = profile_values(renderer, profile)
        check(not values["mgrep"].get("command"), f"Helm {profile} must use default mgrep supervision")
        objects = helm_objects([ROOT / f"values/profiles/{profile}.yaml"])
        check_mgrep_script(container(component(objects, "mgrep"))["command"][2], f"Helm {profile} mgrep")

    custom_values = profile_values(renderer, "matportal", compose=True)
    custom_values["mgrep"]["command"] = "printf custom-command"
    custom = renderer.render(custom_values)["services"]["mgrep"]
    check(custom["command"][2] == "printf custom-command", "custom mgrep command must remain available")


def docker_bundle_run(image: str, command: str, data_dir: Path) -> subprocess.CompletedProcess[str]:
    args = [
        "docker",
        "run",
        "--pull",
        "never",
        "--rm",
        "--network",
        "none",
        "--mount",
        f"type=bind,src={data_dir},dst=/data,readonly",
        "--entrypoint",
        "/bin/sh",
        image,
        "-lc",
        command,
    ]
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=180)


def docker_bundle_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="ontoportal-bundle-regression-") as temporary:
        data_dir = Path(temporary) / "data"
        data_dir.mkdir()
        api = docker_bundle_run(
            API_IMAGE,
            'set -eu; bundle check; bundle exec ruby -e \'require "nokogiri"; require "ontologies_linked_data"; puts Nokogiri::VERSION\'',
            data_dir,
        )
        check(api.returncode == 0, f"API image bundle/import check failed:\n{api.stdout}\n{api.stderr}")
        check("1.18.10" in api.stdout, "API image did not load the pinned Nokogiri")

        cron = docker_bundle_run(
            CRON_IMAGE,
            'set -eu; bundle check; bundle exec ruby -e \'require "active_support/all"; require "ncbo_cron"; puts ActiveSupport::VERSION::STRING\'',
            data_dir,
        )
        check(cron.returncode == 0, f"cron image bundle/import check failed:\n{cron.stdout}\n{cron.stderr}")
        check("5.2.8.1" in cron.stdout, "cron image did not load its baked ActiveSupport")


def compose_specs() -> list[dict[str, Any]]:
    renderer = load_renderer()
    specs = []
    for profile in ["ontoportal-clean", "matportal"]:
        values = profile_values(renderer, profile, compose=True)
        service = renderer.render(values)["services"]["mgrep"]
        image = service["image"]
        repository = image.split("@", 1)[0].rsplit(":", 1)[0]
        specs.append({
            "label": f"Compose {profile}",
            "image": image,
            "digest": MGREP_DIGESTS[repository],
            "entrypoint": service.get("entrypoint"),
            "command": service["command"],
            "port": int(values["mgrep"].get("containerPort") or values["mgrep"]["service"]["port"]),
            "dictionary_path": str(values["mgrep"].get("dictionaryPath", "/data/mgrep/dictionary.txt")),
            "baked_path": "/srv/mgrep/dictionary.txt" if repository.endswith("mgrep-ncbo") else "/srv/mgrep/dictionary/dictionary.txt",
            "compose": True,
        })
    return specs


def helm_specs() -> list[dict[str, Any]]:
    renderer = load_renderer()
    specs = []
    for profile, (repository, digest) in MGREP_PROFILES.items():
        values = profile_values(renderer, profile)
        objects = helm_objects(
            [ROOT / f"values/profiles/{profile}.yaml"],
            [f"images.mgrep.repository={repository}", f"images.mgrep.digest={digest}"],
        )
        service = container(component(objects, "mgrep"))
        image = service["image"]
        check(image == f"{repository}@{digest}", f"Helm {profile} mgrep image override was not rendered")
        specs.append({
            "label": f"Helm {profile}",
            "image": image,
            "digest": digest,
            "entrypoint": None,
            "command": service["command"],
            "port": int(values["mgrep"].get("containerPort") or values["mgrep"]["service"]["port"]),
            "dictionary_path": str(values["mgrep"].get("dictionaryPath", "/data/mgrep/dictionary.txt")),
            "baked_path": "/srv/mgrep/dictionary.txt" if repository.endswith("mgrep-ncbo") else "/srv/mgrep/dictionary/dictionary.txt",
            "compose": False,
        })
    return specs


def check_cached_image(image: str, digest: str) -> None:
    result = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    check(result.returncode == 0, f"cached image is missing: {image}\n{result.stderr}")
    check(digest in result.stdout, f"{image} is not the expected cached digest: {result.stdout}")


def command_for_docker(spec: dict[str, Any]) -> list[str]:
    command = [str(item) for item in spec["command"]]
    if spec["compose"]:
        # Compose writes $$ so its interpolation produces a literal shell $.
        command = [item.replace("$$", "$") for item in command]
    return command


def docker_args(
    spec: dict[str, Any],
    name: str,
    data_dir: Path,
    *,
    detached: bool,
    remove: bool = False,
    extra_mounts: list[tuple[Path, str]] | None = None,
) -> list[str]:
    args = ["docker", "run", "--pull", "never"]
    if detached:
        args.append("-d")
    if remove:
        args.append("--rm")
    args += ["--name", name, "--network", "none", "--mount", f"type=bind,src={data_dir},dst=/data"]
    for source, target in extra_mounts or []:
        args += ["--mount", f"type=bind,src={source},dst={target},readonly"]

    command = command_for_docker(spec)
    if spec["entrypoint"] == []:
        args += ["--entrypoint", ""]
    else:
        # Kubernetes command[] replaces the image entrypoint; mirror that exact
        # rendered command when running the Helm container with Docker.
        check(spec["entrypoint"] is None, f"{spec['label']} has an unexpected entrypoint")
        check(command, f"{spec['label']} has no rendered command")
        args += ["--entrypoint", command[0]]
        command = command[1:]
    args += [spec["image"]] + command
    return args


def dictionary_host_path(data_dir: Path, dictionary_path: str) -> Path:
    relative = Path(dictionary_path).relative_to("/data")
    path = data_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.name == "mgrep":
        path.parent.chmod(0o777)
    return path


def prepare_data_dir(temporary: str) -> Path:
    data_dir = Path(temporary) / "data"
    data_dir.mkdir()
    mgrep_dir = data_dir / "mgrep"
    mgrep_dir.mkdir()
    mgrep_dir.chmod(0o777)
    return data_dir


def inspect_state(name: str) -> tuple[str, int]:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Status}} {{.State.ExitCode}}", name],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    status, code = result.stdout.strip().split()
    return status, int(code)


def wait_for_ready(spec: dict[str, Any], name: str) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        probe = subprocess.run(
            ["docker", "exec", name, "nc", "-z", "127.0.0.1", str(spec["port"])],
            cwd=ROOT,
            capture_output=True,
        )
        if probe.returncode == 0:
            return
        status, _ = inspect_state(name)
        if status != "running":
            break
        time.sleep(0.2)
    logs = subprocess.run(["docker", "logs", name], cwd=ROOT, capture_output=True, text=True)
    raise AssertionError(f"{spec['label']} did not become ready:\n{logs.stdout}\n{logs.stderr}")


def wait_for_exit(name: str) -> int:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status, code = inspect_state(name)
        if status == "exited":
            return code
        time.sleep(0.2)
    raise AssertionError(f"container {name} did not exit")


def start_container(spec: dict[str, Any], data_dir: Path, name: str, extra_mounts: list[tuple[Path, str]] | None = None) -> None:
    result = subprocess.run(
        docker_args(spec, name, data_dir, detached=True, extra_mounts=extra_mounts),
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    check(result.returncode == 0, f"{spec['label']} failed to start:\n{result.stdout}\n{result.stderr}")


def remove_container(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], cwd=ROOT, capture_output=True, text=True)


def docker_mgrep_lifecycle(spec: dict[str, Any]) -> None:
    for mode in ["death", "term"]:
        with tempfile.TemporaryDirectory(prefix="ontoportal-mgrep-regression-") as temporary:
            data_dir = prepare_data_dir(temporary)
            name = f"ontoportal-startup-regression-{os.getpid()}-{mode}-{len(spec['label'])}"
            try:
                start_container(spec, data_dir, name)
                wait_for_ready(spec, name)
                if mode == "death":
                    killed = subprocess.run(["docker", "exec", name, "pkill", "-TERM", "-x", "mgrep"], cwd=ROOT)
                    check(killed.returncode == 0, f"{spec['label']} could not stop mgrep daemon")
                    code = wait_for_exit(name)
                    check(code == 1, f"{spec['label']} daemon loss exit code was {code}, expected 1")
                else:
                    subprocess.run(["docker", "stop", "-t", "5", name], cwd=ROOT, capture_output=True, text=True, check=True)
                    code = wait_for_exit(name)
                    check(code == 143, f"{spec['label']} TERM exit code was {code}, expected 143")
            finally:
                remove_container(name)


def docker_mgrep_dictionary_cases(spec: dict[str, Any]) -> None:
    placeholder = b"0\tDUMMY\n"
    custom = b"0\tCUSTOM\n"

    with tempfile.TemporaryDirectory(prefix="ontoportal-mgrep-regression-") as temporary:
        data_dir = prepare_data_dir(temporary)
        dictionary = dictionary_host_path(data_dir, spec["dictionary_path"])
        dictionary.write_bytes(placeholder)
        name = f"ontoportal-dictionary-placeholder-{os.getpid()}-{len(spec['label'])}"
        try:
            start_container(spec, data_dir, name)
            wait_for_ready(spec, name)
            copied = subprocess.run(
                ["docker", "exec", name, "cmp", "-s", spec["dictionary_path"], spec["baked_path"]],
                cwd=ROOT,
            )
            check(copied.returncode == 0, f"{spec['label']} did not replace the exact dummy dictionary")
        finally:
            subprocess.run(["docker", "stop", "-t", "5", name], cwd=ROOT, capture_output=True, text=True)
            remove_container(name)

    with tempfile.TemporaryDirectory(prefix="ontoportal-mgrep-regression-") as temporary:
        data_dir = prepare_data_dir(temporary)
        dictionary = dictionary_host_path(data_dir, spec["dictionary_path"])
        dictionary.write_bytes(custom)
        name = f"ontoportal-dictionary-custom-{os.getpid()}-{len(spec['label'])}"
        try:
            start_container(spec, data_dir, name)
            wait_for_ready(spec, name)
            check(dictionary.read_bytes() == custom, f"{spec['label']} changed a genuine custom dictionary")
        finally:
            subprocess.run(["docker", "stop", "-t", "5", name], cwd=ROOT, capture_output=True, text=True)
            remove_container(name)

    with tempfile.TemporaryDirectory(prefix="ontoportal-mgrep-regression-") as temporary:
        data_dir = prepare_data_dir(temporary)
        dictionary_host_path(data_dir, spec["dictionary_path"]).write_bytes(placeholder)
        empty_source = Path(temporary) / "empty-dictionary.txt"
        empty_source.touch()
        result = subprocess.run(
            docker_args(
                spec,
                f"ontoportal-dictionary-missing-{os.getpid()}-{len(spec['label'])}",
                data_dir,
                detached=False,
                remove=True,
                extra_mounts=[(empty_source, spec["baked_path"])],
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        check(result.returncode != 0, f"{spec['label']} accepted a dummy dictionary without a baked source")
        check("no usable mgrep dictionary" in result.stderr, f"{spec['label']} missing-source error was not clear")

    with tempfile.TemporaryDirectory(prefix="ontoportal-mgrep-regression-") as temporary:
        data_dir = prepare_data_dir(temporary)
        empty_required = Path(temporary) / "empty-required.txt"
        empty_required.touch()
        result = subprocess.run(
            docker_args(
                spec,
                f"ontoportal-required-file-{os.getpid()}-{len(spec['label'])}",
                data_dir,
                detached=False,
                remove=True,
                extra_mounts=[(empty_required, "/srv/mgrep/word_divider.txt")],
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        check(result.returncode != 0, f"{spec['label']} accepted a missing required mgrep file")
        check("required mgrep file is missing" in result.stderr, f"{spec['label']} missing-file error was not clear")


def docker_mgrep_checks() -> None:
    specs = compose_specs() + helm_specs()
    for spec in specs:
        repository = spec["image"].split("@", 1)[0].rsplit(":", 1)[0]
        check_cached_image(spec["image"], spec["digest"])
        check(repository in MGREP_DIGESTS, f"{spec['label']} uses an unapproved mgrep image variant")
        docker_mgrep_dictionary_cases(spec)
        docker_mgrep_lifecycle(spec)


def main() -> int:
    static_checks()
    if os.environ.get("STARTUP_DOCKER_TESTS") == "1":
        check(shutil.which("docker") is not None, "STARTUP_DOCKER_TESTS=1 requires docker")
        docker_bundle_checks()
        docker_mgrep_checks()
        print("startup regression passed (Helm, Compose, and Docker image checks)")
    else:
        print("startup regression passed (Helm and Compose checks; set STARTUP_DOCKER_TESTS=1 for image checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
