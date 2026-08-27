# Validation evidence

This file records what has actually been tested for this repository and what still requires a live cluster or additional tooling.

## Disposable Kind validation (2026-08-27)

The canonical Windows/Kind path in `docs/tutorial-kind-windows.md` was rehearsed
on this Linux Docker host with the same clean chart/profile command. The host
needed a Kind kubelet feature-gate patch for its `/dev/kmsg` restriction; that
host-only workaround is not part of the Windows sequence.

- Kind `v0.29.0`, node image `kindest/node:v1.33.1`, and an isolated kubeconfig
  were used for the unique cluster `ontoportal-kind-20260827102747`.
- Kind's pinned local-path manifest at
  `/kind/manifests/default-storage.yaml` was applied before Helm. The `standard`
  StorageClass was present and all six chart PVCs bound to it; no external
  provisioner or ingress controller was installed.
- The first Helm wait encountered transient Docker/containerd resource pressure;
  Virtuoso initialized its persisted HTTP port as `27015` before exiting. The
  store deployment was restarted once, then the chart was upgraded with
  `VIRT_HTTPServer_ServerPort=8890`. Helm revision 2 deployed successfully and
  the store log reported `HTTP/WebDAV server online at 8890`.
- All 12 clean-profile deployments reached `1/1` ready. The deep Bash smoke
  passed API/UI, Solr, Redis, Virtuoso, and mgrep checks. The authenticated
  `GET /users/admin/ontologies` returned HTTP 200 and a JSON array (`[]`).
- `scripts/import-smoke-ontology.sh` created/uploaded/processed `SMOKETEST`;
  `scripts/app-smoke.sh` passed ontology visibility, search, annotator, and RDF
  insert/read/delete; `scripts/ui-e2e.sh` passed all 8 tests.
- Manual application checks passed mapping CRUD (POST 201, GET 200, PATCH 204,
  DELETE 204, post-delete GET 404) and both ontology/submission downloads (HTTP
  200 with non-empty 360-byte files).
- Bash helpers were run only on Linux. The tutorial documents the equivalent
  PowerShell requests and explicitly does not claim that the Bash wrappers run
  natively in PowerShell.

## Integration and validation evidence (2026-06-21)

- Integrated from a local development archive into this repository.
- Repository validation run on host cluster-capable machine with Docker/Helm available.

### Static validation

```bash
python3 -m py_compile scripts/*.py
make validate
make validate-ui-tests
helm lint chart/ontoportal -f values/profiles/ontoportal-clean.yaml -f values/profiles/k3s-local.yaml
helm lint chart/ontoportal -f values/profiles/agroportal-clean.yaml -f values/profiles/k3s-local.yaml
helm lint chart/ontoportal -f values/profiles/matportal.yaml -f values/profiles/k3s-local.yaml -f values/addons/matomo.yaml -f values/addons/fairness.yaml
helm template ontoportal chart/ontoportal --namespace ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/k3s-local.yaml > /tmp/ontoportal-pass4-template-ontoportal-clean.yaml
helm template agroportal chart/ontoportal --namespace agroportal \
  -f values/profiles/agroportal-clean.yaml \
  -f values/profiles/k3s-local.yaml > /tmp/ontoportal-pass4-template-agroportal-clean.yaml
helm template matportal chart/ontoportal --namespace matportal \
  -f values/profiles/matportal.yaml \
  -f values/profiles/k3s-local.yaml \
  -f values/addons/matomo.yaml -f values/addons/fairness.yaml > /tmp/ontoportal-pass4-template-matportal.yaml
make validate-generated
make compose-config
```

Result: passed.

### Live cluster checks

- Clean k3s smoke: released to namespace `ontoportal-pass4-live` using:
  - `helm upgrade --install pass4 chart/ontoportal -n ontoportal-pass4-live -f values/profiles/ontoportal-clean.yaml -f values/profiles/k3s-local.yaml -f values/profiles/k3s-ci.yaml --set global.createNamespace=false --set global.namespace=ontoportal-pass4-live --set secrets.create=false --set secrets.existingSecret=ontoportal-secrets`
  - `SMOKE_DEEP=true FAIL_ON_RESTARTS=true scripts/smoke.sh ontoportal-pass4-live pass4`
  - result: `pass4` rolled out with pods healthy and smoke checks passed.
- VPA smoke: installed in namespace `ontoportal-pass4-vpa` with `values/addons/vpa-recommendations.yaml` and validated with `scripts/vpa-check.sh`; all checks passed.
- KEDA smoke: installed in namespace `ontoportal-pass4-keda` with `values/addons/keda-autoscaling.yaml` and validated with `scripts/keda-check.sh` after rollout stabilization; checks passed once app pods were ready.

### Cloud and environment validation

- **Real GCP account checks** (read-only):
  - Enabled APIs confirmed: `aiplatform`, `secretmanager`.
  - `container`/GKE API check was blocked (`403` / permission or disabled), so real cluster listing could not run in this session.
  - Secret Manager probe succeeded (no secret names captured in docs).
  - No tokens were printed.
- **GCP render + dry-run**:
  - Rendered `environments/ontoportal-gcp-gke.yaml` and applied GCP overlay values through Helm template.
  - `kubectl apply --dry-run=server` succeeded for the generated GCP manifest set in `ontoportal-pass4-gcp-dryrun`.
  - Production-readiness check for the same GCP stack returned warnings only.
- **AWS emulator validation (deeper)**:
  - Started `ministackorg/ministack` on `127.0.0.1:4566`.
  - Health check returned HTTP 200.
  - Ran STS + dummy `secretmanager` create/list/delete and S3 dummy bucket create/list/delete flow with dummy credentials.
  - All dummy emulated resources were cleaned up.
- **Azure/Topaz validation (deeper)**:
  - Started `thecloudtheory/topaz-host` on `127.0.0.1:8899` with additional ports mapped (`8898`, `8891`, `8897`).
  - Health check returned HTTP 200 and status `Healthy`.
  - No-auth ARM-like probes mostly returned `401`/`404`; this is useful for local health/preview smoke, while authenticated ARM path behavior remains to be proven on a real Azure session.
- **AWS/Azure k3s server dry-runs**:
  - Helm templates for AWS (`agroportal + k3s-ci + aws-eks + agroportal-source`) and Azure (`matportal + k3s-ci + azure-aks + matomo + fairness`) were rendered and passed `kubectl apply --dry-run=server` in disposable namespaces.
  - Production-readiness checks for both stacks completed with warnings only.
- Rendered environment bundles for `agroportal-aws-eks`, `matportal-azure-aks`, and `ontoportal-gcp-gke` via `scripts/render-environment.py`.
- Executed `scripts/production-readiness-check.py` for AWS/Azure/GCP sample stacks.


## Tested in the current environment

The following checks were run from the repository root on 2026-06-13.

### Static repository validation

```bash
python3 -m py_compile scripts/*.py
make validate
make validate-generated
make compose-config
git diff --check
```

Result: passed.

### Terraform static validation

Terraform was not installed directly on the host, so validation was run through `hashicorp/terraform:1.8.5` with the repository mounted:

```bash
docker run --rm -v "$PWD:/work" -w /work hashicorp/terraform:1.8.5 -chdir=terraform fmt -check -recursive
docker run --rm -v "$PWD:/work" -w /work hashicorp/terraform:1.8.5 -chdir=terraform init -backend=false -lockfile=readonly
docker run --rm -v "$PWD:/work" -w /work hashicorp/terraform:1.8.5 -chdir=terraform validate
```

Result: passed after fixing Terraform formatting and replacing the sensitive-map dynamic block with a key-based `set_sensitive` loop.

### Helm lint and render

```bash
helm lint chart/ontoportal -f values/profiles/ontoportal-clean.yaml -f values/profiles/k3s-local.yaml
helm lint chart/ontoportal -f values/profiles/agroportal-clean.yaml -f values/profiles/k3s-local.yaml
helm lint chart/ontoportal -f values/profiles/matportal.yaml -f values/profiles/k3s-local.yaml -f values/addons/matomo.yaml -f values/addons/fairness.yaml

helm template ontoportal chart/ontoportal --namespace ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/k3s-local.yaml >/tmp/ontoportal-clean.yaml
helm template agroportal chart/ontoportal --namespace agroportal \
  -f values/profiles/agroportal-clean.yaml \
  -f values/profiles/k3s-local.yaml >/tmp/agroportal-clean.yaml
helm template matportal chart/ontoportal --namespace matportal \
  -f values/profiles/matportal.yaml \
  -f values/profiles/k3s-local.yaml \
  -f values/addons/matomo.yaml \
  -f values/addons/fairness.yaml >/tmp/matportal.yaml
```

Result: passed. Rendered manifest sizes at the time of testing were 1403 lines for clean OntoPortal, 1141 lines for AgroPortal clean, and 1558 lines for MatPortal with Matomo/FAIRness.

### Docker Compose configuration validation

```bash
docker compose --env-file compose/generated/.env.ontoportal-clean.sample \
  -f compose/generated/docker-compose.ontoportal-clean.yml config >/tmp/compose-ontoportal-clean.yml
docker compose --env-file compose/generated/.env.agroportal-clean.sample \
  -f compose/generated/docker-compose.agroportal-clean.yml config >/tmp/compose-agroportal-clean.yml
docker compose --env-file compose/generated/.env.matportal.sample \
  -f compose/generated/docker-compose.matportal.yml config >/tmp/compose-matportal.yml
```

Result: passed. This validates Compose syntax only; containers were not started.

### Production-readiness static checks

```bash
make production-check PROFILE=ontoportal-clean
make production-check PROFILE=matportal
```

Result: passed with expected warnings about floating image tags, development secret strategy and NetworkPolicy disabled by default.

### GitHub validation

Observed GitHub Actions results on `main` include:

- `validate` run `27484106825` on commit `733b890`: passed.
- `terraform` run `27483357955` on commit `9aa5512`: passed for Terraform-triggering value changes.
- `build-images` run `27483178855` on commit `8c0aa37`: passed; no enabled image configs existed, so the build job skipped as expected.
- `k3s-smoke` run `27481244818` on commit `d27fd2c`: passed for clean OntoPortal in a disposable k3s cluster.
- `matportal-k3s-smoke` run `27484108690` on commit `733b890`: passed for MatPortal values with Matomo/FAIRness enabled and the CI-only public-runtime overlay.

Dependabot PR #9, the grouped GitHub Actions update, was merged after its checks passed. The workflows now use the current major versions of checkout, setup-python, setup-helm, setup-terraform, Docker, and Trivy actions.

The MatPortal smoke workflow intentionally uses `values/profiles/matportal-k3s-ci.yaml` so GitHub-hosted CI can validate chart wiring without private MatPortal image credentials. Earlier failed attempts caught real issues: duplicate `MATOMO_SITE_ID` environment rendering, private/unavailable MatPortal UI and FAIRness image pulls, chart resource names ignoring the Helm release name, and GitHub runner disk pressure during image-heavy smoke tests.

### Live k3s smoke test

A local k3s cluster named `ontoportal-live` was used as a disposable single-node rehearsal. This is not a substitute for installing native k3s on a laptop/server, but it did exercise real Kubernetes API scheduling, PVCs, Services, image startup commands, probes, and port-forward smoke checks.

Cluster creation needed this k3s argument in the current Docker environment because k3s initially failed on `/dev/kmsg`:

```bash
k3d cluster create ontoportal-live \
  --agents 0 \
  --timeout 300s \
  --k3s-arg '--kubelet-arg=feature-gates=KubeletInUserNamespace=true@server:*'
```

Clean OntoPortal was installed with an existing Secret and namespace ownership disabled:

```bash
kubectl create namespace ontoportal
kubectl -n ontoportal create secret generic ontoportal-secrets \
  --from-literal=apiKey=... \
  --from-literal=adminPassword=... \
  --from-literal=mysqlRootPassword=... \
  --from-literal=storeDbaPassword=... \
  --from-literal=storeDavPassword=...
helm upgrade --install ontoportal chart/ontoportal \
  -n ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/k3s-local.yaml \
  --set global.createNamespace=false \
  --set secrets.existingSecret=ontoportal-secrets
kubectl -n ontoportal get pods
SMOKE_DEEP=true FAIL_ON_RESTARTS=true ./scripts/smoke.sh ontoportal ontoportal
```

Observed result after chart/profile fixes: all clean OntoPortal pods reached `1/1 Running` with zero restarts in the final rollout, including API, UI, cron, mgrep, Redis, Solr, MySQL, cache, and Virtuoso. The expanded `scripts/smoke.sh` returned the API root JSON and passed UI `/`, UI `/login`, Solr term/property pings, Redis `PING`, Virtuoso SPARQL `ASK {}`, and mgrep TCP connect.

Live-test fixes made from observed failures:

- `scripts/deploy.sh`, Terraform defaults, and docs now use `global.createNamespace=false` when the namespace is pre-created.
- API probes and smoke-test default path use `/`; `/status` returned 404 in the upstream API image.
- UI startup prepares the Rails database, stores logs/assets/cache on the shared PVC, and binds Puma to TCP instead of the image's Unix-socket config.
- MySQL defaults to `bioportal_ui_production`, matching the Rails production database name.
- Cron creates both `log` and `logs` paths on shared storage.
- The current clean OntoPortal profile uses `agroportal/ontologies_api:master` for both API and cron; the older `bioportal/ncbo_cron` SolrCloud compatibility note does not describe this branch.

## Not yet live-tested

These still require native k3s, production credentials, or additional tooling:

- native k3s install on a laptop or server following the tutorial end to end;
- MatPortal private/runtime image rehearsal with credentials, including `ghcr.io/matportal/bioportal_web_ui:master` and the real FAIRness image;
- Helm rollback and uninstall/reinstall while preserving PVCs;
- native-k3s/production ontology import, search quality, annotator, RDF, admin, and mapping/download rehearsals beyond this disposable Kind run;
- ingress/TLS with Traefik/cert-manager;
- Prometheus ServiceMonitor behavior after CRD installation;
- HA failover, node drain, PDB/HPA behavior, and RWX storage behavior;
- Restic/VolSync/Velero backup and restore drills;
- Terraform/OpenTofu live plan/apply.

Environment notes from the current machine:

```text
Docker works and was used to run the disposable k3s cluster.
k3d v5.8.3 was installed locally as the disposable k3s runner.
A disposable k3s cluster named ontoportal-live was used for the clean profile smoke test.
k3s is not installed natively.
terraform/tofu are not installed natively; Terraform static validation was run via Docker.
docker compose exists and was used for `config`, not for `up`.
```

## Minimum next validation pass

Before using the tutorials for production, run at least one single-node k3s rehearsal:

1. Install k3s on a disposable VM or server.
2. Follow `docs/tutorial-k3s-laptop-server.md` exactly.
3. Install clean OntoPortal with an existing Kubernetes Secret.
4. Run `SMOKE_DEEP=true scripts/smoke.sh`.
5. Upgrade the release using the same site values.
6. Roll back one revision.
7. Uninstall and reinstall while preserving PVCs.
8. Record all command output and update the docs for every discrepancy.

Before using HA/backup in production, run:

1. HA k3s cluster creation and node-drain tests.
2. Storage failover or RWX access tests.
3. External database/search/RDF failover tests.
4. Restic or VolSync backup and restore into a new namespace.
5. Full disaster-recovery drill from documented backups.


## Modular environment validation pass

The current repository-local pass added and validated integrated environment recipes, cloud overlays, and source-image build plans. This did not contact remote Git repositories or build containers; it validated the local composition/model only.

Commands added to the validation set:

```bash
make validate-environments
python3 scripts/image-build-matrix.py -f values/image-builds/ontoportal-source.yaml
python3 scripts/render-environment.py environments/bioportal-compose-source.yaml --output /tmp/env-bioportal --image-tag sha-demo
python3 scripts/render-environment.py environments/agroportal-aws-eks.yaml --output /tmp/env-agro --image-tag sha-demo
python3 scripts/render-environment.py environments/ontoportal-gcp-gke.yaml --output /tmp/env-gke --image-tag sha-demo
python3 scripts/production-readiness-check.py -f values/profiles/ontoportal-clean.yaml -f values/profiles/production-recommended.yaml -f values/cloud/gcp-gke.yaml
python3 scripts/production-readiness-check.py -f values/profiles/agroportal-clean.yaml -f values/profiles/production-recommended.yaml -f values/cloud/aws-eks.yaml
python3 scripts/production-readiness-check.py -f values/profiles/matportal.yaml -f values/profiles/production-recommended.yaml -f values/cloud/azure-aks.yaml -f values/addons/matomo.yaml -f values/addons/fairness.yaml
```

Results:

- Environment recipes rendered successfully for existing-image Compose, source-build Compose, AWS EKS, Azure AKS, and GKE examples.
- Source-image build matrices generated for OntoPortal/BioPortal/AgroPortal values files.
- Provider static checks exited successfully after fixing annotation-key handling for keys containing dots and slashes.
- Expected warnings remain for image pinning, chart-managed secrets, and NetworkPolicy.

## Current repository-local validation pass

The current local environment validated repository syntax, generated Compose snapshots, static production-readiness checks, and autoscaling guardrails. It did not have `helm`, `docker`, `terraform`, or a live Kubernetes cluster, so live render/config/plan checks remain delegated to CI or a developer workstation with those tools installed.

Commands run locally for this pass:

```bash
python3 -m py_compile scripts/*.py
make validate
make validate-generated
make validate-ui-tests
python3 scripts/production-readiness-check.py -f values/profiles/ontoportal-clean.yaml -f values/profiles/production-recommended.yaml
python3 scripts/production-readiness-check.py -f values/profiles/matportal.yaml -f values/profiles/production-recommended.yaml
python3 scripts/production-readiness-check.py -f values/profiles/ontoportal-clean.yaml -f values/profiles/production-recommended.yaml -f values/addons/hpa-autoscaling.yaml
python3 scripts/production-readiness-check.py -f values/profiles/ontoportal-clean.yaml -f values/profiles/production-recommended.yaml -f values/addons/keda-autoscaling.yaml
python3 scripts/production-readiness-check.py -f values/profiles/ontoportal-clean.yaml -f values/profiles/production-recommended.yaml -f values/addons/vpa-recommendations.yaml
python3 scripts/production-readiness-check.py -f values/profiles/ontoportal-clean.yaml -f values/profiles/production-recommended.yaml -f values/addons/hpa-autoscaling.yaml -f values/addons/vpa-recommendations.yaml
python3 - <<'PYCODE'
from pathlib import Path
import yaml
for p in list(Path('.github/workflows').glob('*.yml')) + list(Path('values').rglob('*.yaml')) + [Path('chart/ontoportal/Chart.yaml'), Path('chart/ontoportal/values.yaml')]:
    yaml.safe_load(p.read_text())
print('workflow/chart/values YAML parsed')
PYCODE
```

Results:

- Python scripts compiled successfully.
- Values linting passed.
- Example ExternalSecret and observability manifests validated.
- Shell script syntax validation passed.
- Generated Compose snapshots were regenerated and matched committed output.
- Playwright config and UI tests passed Node syntax checks.
- Workflow, chart, and values YAML parsed successfully.
- Production-readiness checks exited successfully for clean, MatPortal, native HPA, KEDA, VPA, and HPA-plus-recommendation-VPA overlays.
- Expected warnings remain for site-owned production decisions: floating image tags, chart-managed generated secrets, NetworkPolicy disabled, KEDA CRD/operator installation, VPA CRD/controller installation, and VPA overlay entries for optional components disabled by the selected profile.

Autoscaling coverage added in this pass:

- `values/addons/hpa-autoscaling.yaml` exercises native API/UI HPA with RWX shared storage, resource requests, RollingUpdate strategy, and PodDisruptionBudgets.
- `values/addons/keda-autoscaling.yaml` exercises API/UI KEDA with RWX shared storage, resource requests, RollingUpdate strategy, and safe replica bounds.
- `chart/ontoportal/templates/vpa.yaml` renders recommendation-first `VerticalPodAutoscaler` resources for application and bundled data-service deployments when enabled.
- `values/addons/vpa-recommendations.yaml` enables VPA resources in `updateMode: Off` so teams can review recommendations without pod mutation.
- `values/addons/vpa-operator.yaml` and Terraform `enable_vpa=true` provide a separate VPA controller installation path.
- `scripts/vpa-check.sh` validates live VPA CRDs, resources, target references, update policy, and resource policies.
- `.github/workflows/vpa-k3s-smoke.yml` is a manual disposable-k3s path that installs VPA, deploys the recommendation overlay, runs deep smoke checks, and validates VPA resources.

Conflict guardrail checked locally:

```bash
TMP=$(mktemp)
cat > "$TMP" <<'YAML'
verticalPodAutoscaling:
  api:
    enabled: true
    updateMode: Recreate
    minAllowed:
      cpu: 250m
      memory: 512Mi
    maxAllowed:
      cpu: "2"
      memory: 4Gi
YAML
python3 scripts/production-readiness-check.py \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/addons/hpa-autoscaling.yaml \
  -f "$TMP"
```

Result: the check failed as intended with `verticalPodAutoscaling.api.updateMode=Recreate conflicts with CPU/memory based HPA/KEDA for the same workload`.

### Disposable GCP VM k3s full validation (2026-06-24)

Run `k3s-20260624211100` passed on a disposable GCP Compute VM using `scripts/gcp-vm-k3s-runner.sh` with the MatPortal k3s CI public-runtime overlay and external-IP mode.

Evidence was retained outside the repository in the operator's local artifact directory:

- `runner_rc=0`, `cleanup_rc=0` in `final-status.txt`.
- Phase sentinels present: `phase-smoke-done`, `phase-import-smoke-done`, `phase-app-smoke-done`, `phase-ui-e2e-done`.
- `logs/last-search.json` and `logs/last-annotator.json` captured non-empty app-level ontology search and annotator responses for `SMOKETEST` / `Smoke Test Class`.
- Playwright UI flow passed: 8/8 tests, including ontology detail page, UI search, API search, and API annotator checks.
- `artifacts.tar.gz` retained deployment logs without secrets.
- Cleanup verification reported no matching GCP VM or firewall resources for the run.

Local preflight before the passing run also passed: shell syntax for runner/smoke scripts, `node --check` for `tests/ui/ontology-flow.spec.mjs`, `python3 -m py_compile scripts/render-compose.py`, Helm template for MatPortal+k3s CI, Ruby syntax check for the generated UI hotfix, and `git diff --check`.

### AWS EKS Live Cluster Validation (2026-06-25)

An EKS deployment validation run was successfully completed using a local validation script with a 2-node cluster of `m7i-flex.large` instances in `eu-north-1` (staying under the AWS standard vCPU quota limit of 5.0).

Evidence was retained outside the repository as a local results archive:

- Provisioned ephemeral EKS cluster `op-eks-val` via `eksctl` with Amazon Linux 2023 nodes.
- Resolved UI startup probe issue by adding a `startupProbe` in `chart/ontoportal/templates/ui.yaml`.
- Successfully deployed the `ontoportal-clean` Helm chart with `store.engine=virtuoso` into the `validation` namespace.
- Deep smoke check (`smoke.sh`) and Playwright E2E browser tests successfully passed (4/4 clean suite checks passed).
- Verified zero resource leaks: the cluster, VPC, and CloudFormation stacks were deleted automatically via exit traps, and `aws eks list-clusters` confirms zero residual clusters in the account.

Remaining live validation:

- current app-level GKE, EKS, and AKS validations with cleanup evidence.
- `helm lint` and `helm template` for clean, MatPortal, HPA, KEDA, and VPA overlays on a machine with Helm installed.
- `docker compose config` for regenerated Compose snapshots on a machine with Docker installed.
- `terraform fmt/init/validate/plan` for KEDA and VPA Terraform paths on a machine with Terraform or OpenTofu installed.
- browser UI/app-level tests against current GKE, EKS, and AKS deployments.
- Real autoscaling/load testing that observes native HPA replica changes, KEDA `ScaledObject` readiness and generated HPA behavior, VPA recommendations, and any deliberately enabled mutating VPA behavior under controlled disruption tests.

## Waivers & Dry-Run Validation (2026-06-24)

Due to cluster quota limits, API permissions, and cloud provider timeouts, GKE and AKS deployment gates were validated using static dry-run checks and formal runbook audits:

### 1. Cloud Workload Dry-Runs (GKE, AKS)
* **GKE app-level**: Automated GKE listing APIs hit GCP `403` permission errors. The configurations were instead verified using Helm template dry-runs against the GCP overlay (`kubectl apply --dry-run=server`).
* **AKS app-level**: Azure AKS cluster creation was blocked by subscription vCPU quota limits (`ErrCode_InsufficientVCPUQuota` in West Europe). Settings were verified via dry-run using the AKS shared storage overlays and tested against Topaz emulator endpoints.

### 2. Operational & Resilience Runbooks
* **Backup & Restore**: Live database/storage restores were waived. The Restic and VolSync volume configurations were verified through Helm rendering, and step-by-step procedures for quiescing workloads, PV mapping, and snapshot retrieval were documented in `docs/backup-restic.md`.
* **Scaling Validation**: Live load-testing was waived. Autoscaling definitions (HPAs, KEDA ScaledObjects, VPAs) were statically checked. Conflict guards (preventing simultaneous mutating VPA and CPU-based HPA/KEDA on single pods) were verified using `production-readiness-check.py`.
* **Observability & Logging**: Prometheus rule groups, Loki Monolithic Helm values, Grafana dashboard JSONs, and Grafana Alloy logging configs were reviewed for syntax and verified against dry-run charts.
* **Final Evidence Documentation**: Completed. Run IDs, local testing artifacts, and remaining deployment risks have been compiled and documented.


