#!/usr/bin/env python3
"""Cheap repository validation without requiring Helm or Docker.

It validates YAML syntax, checks that profiles keep MatPortal-only behavior gated,
and renders every Compose profile to catch cross-profile drift early in CI.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Any, Dict

import yaml


class UniqueKeyLoader(yaml.SafeLoader):
    """YAML loader that rejects duplicate mapping keys.

    PyYAML silently keeps the last duplicate key by default, which can hide
    broken values overlays. Validation should fail instead.
    """


def construct_unique_mapping(loader: UniqueKeyLoader, node: yaml.nodes.MappingNode, deep: bool = False) -> Dict[Any, Any]:
    mapping: Dict[Any, Any] = {}
    seen: set[Any] = set()
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        seen.add(key)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping)

ROOT = pathlib.Path(__file__).resolve().parents[1]
YAML_GLOBS = ["chart/ontoportal/values.yaml", "values/**/*.yaml", "compose/generated/*.yml", "*.yaml", ".github/**/*.yml"]
ALLOWED_IMAGE_PREFIXES = ("ghcr.io/matportal/", "docker.io/matportal/")


def read_yaml(path: pathlib.Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.load(fh, Loader=UniqueKeyLoader)


def validate_yaml() -> None:
    seen = set()
    for pattern in YAML_GLOBS:
        for path in ROOT.glob(pattern):
            if path in seen or path.name.startswith(".") and path.suffix not in {".yml", ".yaml"}:
                continue
            seen.add(path)
            try:
                read_yaml(path)
            except Exception as exc:  # noqa: BLE001 - validation script
                raise SystemExit(f"YAML parse failed: {path.relative_to(ROOT)}: {exc}") from exc


def validate_profiles() -> None:
    clean = read_yaml(ROOT / "values/profiles/ontoportal-clean.yaml") or {}
    mat = read_yaml(ROOT / "values/profiles/matportal.yaml") or {}
    if clean.get("profile", {}).get("matportal"):
        raise SystemExit("ontoportal-clean must not set profile.matportal=true")
    if (clean.get("patches", {}).get("matportalApiParentNormalization", {}) or {}).get("enabled"):
        raise SystemExit("ontoportal-clean must not enable MatPortal API parent normalization")
    if not mat.get("profile", {}).get("matportal"):
        raise SystemExit("matportal profile should set profile.matportal=true")


def render_compose_profiles() -> None:
    for profile in ["ontoportal-clean", "agroportal-clean", "matportal"]:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/render-compose.py"), "-f", f"values/profiles/{profile}.yaml", "-f", "values/profiles/docker-compose.yaml"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )


def validate_no_hardcoded_matportal_services() -> None:
    forbidden = ["matportal-api", "matportal-ui", "matportal-store", "matportal-solr", "matportal-cache"]
    for path in (ROOT / "chart" / "ontoportal" / "templates").glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                raise SystemExit(f"hard-coded old service name {token!r} found in {path.relative_to(ROOT)}")


def ensure_repo_relative(value: str, field: str, source: pathlib.Path) -> pathlib.Path:
    path = (ROOT / value).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise SystemExit(f"{source.relative_to(ROOT)}: {field} must stay inside the repository: {value}") from exc
    return path


def validate_image_build_configs() -> None:
    for path in sorted((ROOT / "images").glob("*/image.json")):
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - validation script
            raise SystemExit(f"JSON parse failed: {path.relative_to(ROOT)}: {exc}") from exc
        if not isinstance(config, dict):
            raise SystemExit(f"{path.relative_to(ROOT)} must contain a JSON object")
        enabled = config.get("enabled", False)
        if not isinstance(enabled, bool):
            raise SystemExit(f"{path.relative_to(ROOT)}: enabled must be a JSON boolean")
        push = config.get("push", True)
        if not isinstance(push, bool):
            raise SystemExit(f"{path.relative_to(ROOT)}: push must be a JSON boolean when present")
        if not enabled:
            continue
        image = str(config.get("image", "")).strip()
        if not image:
            raise SystemExit(f"{path.relative_to(ROOT)}: image is required when enabled=true")
        if not image.startswith(ALLOWED_IMAGE_PREFIXES):
            allowed = ", ".join(ALLOWED_IMAGE_PREFIXES)
            raise SystemExit(f"{path.relative_to(ROOT)}: image must start with one of: {allowed}")
        context = ensure_repo_relative(str(config.get("context") or path.parent.relative_to(ROOT)), "context", path)
        if not context.exists():
            raise SystemExit(f"{path.relative_to(ROOT)}: context does not exist: {context.relative_to(ROOT)}")
        dockerfile = ensure_repo_relative(str(config.get("dockerfile") or context.relative_to(ROOT) / "Dockerfile"), "dockerfile", path)
        if not dockerfile.is_file():
            raise SystemExit(f"{path.relative_to(ROOT)}: dockerfile does not exist: {dockerfile.relative_to(ROOT)}")
        try:
            dockerfile.relative_to(context)
        except ValueError as exc:
            raise SystemExit(
                f"{path.relative_to(ROOT)}: dockerfile must be inside context: "
                f"{dockerfile.relative_to(ROOT)} not under {context.relative_to(ROOT)}"
            ) from exc
        if push and context == ROOT:
            raise SystemExit(f"{path.relative_to(ROOT)}: publishing from repository root is not allowed; use a narrower image context")


def validate_runtime_solr_compatibility() -> None:
    helpers_text = (ROOT / "chart" / "ontoportal" / "templates" / "_helpers.tpl").read_text(encoding="utf-8")
    if "SOLR_TERM_SEARCH_URL.to_s.sub(%r{/term_search_core1/?\\z}" not in helpers_text:
        raise SystemExit("Runtime config must strip /term_search_core1 for Solr base URL compatibility")
    if (
        "module Administration" not in helpers_text
        or "solr_alive?" not in helpers_text
        or "fetch_all_collections" not in helpers_text
        or "create_collection" not in helpers_text
        or "class SolrConnector" not in helpers_text
    ):
        raise SystemExit("Runtime config must override SOLR::Administration and SOLR::SolrConnector")
    if "@cache.invalidate(graph.to_s)" in helpers_text:
        raise SystemExit("Cache invalidation must pass graph object directly, not graph.to_s")
    if "@cache.invalidate(graph)" not in helpers_text:
        raise SystemExit("Cache invalidation must pass graph object directly")


def validate_virtuoso_port() -> None:
    store_tpl = (ROOT / "chart" / "ontoportal" / "templates" / "store.yaml").read_text(encoding="utf-8")
    expected = '            - name: VIRT_HTTPServer_ServerPort\n              value: "8890"'
    if expected not in store_tpl:
        raise SystemExit("Virtuoso HTTP server port must be pinned to the Service port 8890")


def validate_solr_and_cron_fallbacks() -> None:
    cron_tpl = (ROOT / "chart" / "ontoportal" / "templates" / "cron.yaml").read_text(encoding="utf-8")
    solr_tpl = (ROOT / "chart" / "ontoportal" / "templates" / "solr.yaml").read_text(encoding="utf-8")
    render_py = (ROOT / "scripts" / "render-compose.py").read_text(encoding="utf-8")

    if 'name="resource_model"' not in solr_tpl or 'name="resource_model"' not in render_py:
        raise SystemExit("Solr schema setup in Helm and Compose renderer must configure resource_model field")

    if 'NCBO_IMPORT="ncbo_ontology_import"' not in cron_tpl or 'NCBO_IMPORT="ncbo_ontology_import"' not in render_py:
        raise SystemExit("Starter ontology import must support executable fallback in Helm and Compose")

    if 'CRON_CMD={{ .Values.cron.startCommand | quote }}' not in cron_tpl:
        raise SystemExit("Helm cron startup must honor custom startCommand with safe fallback")


def main() -> None:
    validate_yaml()
    validate_profiles()
    validate_no_hardcoded_matportal_services()
    validate_runtime_solr_compatibility()
    validate_virtuoso_port()
    validate_solr_and_cron_fallbacks()
    validate_image_build_configs()
    render_compose_profiles()
    print("validation passed")


if __name__ == "__main__":
    main()
