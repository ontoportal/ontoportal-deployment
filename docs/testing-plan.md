# Testing plan

This repository has static/render validation, but a deployment repository is not trustworthy until the tutorials have been rehearsed on real k3s clusters and restores have been proven. Use this plan to decide what to test next and how to record evidence.

## Current evidence

See `docs/validation-evidence.md` for commands already run and explicit gaps. Current passing checks include static validation, CI Helm lint/render, CI Compose `config`, production-readiness warnings, GitHub Actions validation, Playwright UI smoke tests, clean OntoPortal k3s smoke, MatPortal k3s smoke with the CI-only public-runtime overlay, KEDA/VPA render checks, and manual KEDA/VPA k3s smoke workflows. Native k3s install, private MatPortal image rehearsal, HA failover, HPA/KEDA load testing, VPA recommendation review under load, Terraform apply, and backup/restore drills still need real-cluster testing.

## Done-until-done guardrail

`docs/deployment-gates.tsv` is the deployment gate checklist. Before anyone says the whole pass is done, run:

```bash
make check-gates
```

It must fail while any required gate is pending. To run a watcher that monitors the gate checklist until all items pass or are waived, run:

```bash
make watch-gates
```

The watcher writes `/tmp/ontoportal-validation-status.md` by default and exits only when all required gates are complete.

## Test matrix

| Target | Profile/files | Required result |
| --- | --- | --- |
| Static values/scripts | repository root | `make validate`, `make validate-generated`, `make validate-ui-tests`, and optional Docker-backed `make compose-config` pass |
| Helm clean | `ontoportal-clean.yaml`, `k3s-local.yaml` | `helm lint` and `helm template` pass |
| Helm AgroPortal clean | `agroportal-clean.yaml`, `k3s-local.yaml` | `helm lint` and `helm template` pass without MatPortal patches |
| Helm MatPortal | `matportal.yaml`, `k3s-local.yaml`, Matomo/FAIRness | `helm lint` and `helm template` pass |
| Helm HPA overlay | `ontoportal-clean.yaml`, `production-recommended.yaml`, `hpa-autoscaling.yaml` | `helm template` renders native HPAs and RollingUpdate API/UI strategy |
| Helm KEDA overlay | `ontoportal-clean.yaml`, `production-recommended.yaml`, `keda-autoscaling.yaml` | `helm template` renders KEDA ScaledObjects; `.github/workflows/keda-k3s-smoke.yml` installs KEDA and checks generated ScaledObjects/HPAs in k3s |
| Helm VPA overlay | `ontoportal-clean.yaml`, `production-recommended.yaml`, `vpa-recommendations.yaml` | `helm template` renders recommendation-only VPAs; `.github/workflows/vpa-k3s-smoke.yml` installs VPA and checks generated VPA targets in k3s |
| Browser UI smoke | deployed UI/API | Playwright checks home, login, keyboard focus, critical assets, and API non-500 response |
| k3s CI clean | `.github/workflows/k3s-smoke.yml`, `values/profiles/k3s-ci.yaml` | scheduled/manual GitHub Actions job installs clean OntoPortal and runs deep smoke |
| k3s CI MatPortal | `.github/workflows/matportal-k3s-smoke.yml`, MatPortal profile, `k3s-ci.yaml`, `matportal-k3s-ci.yaml`, Matomo/FAIRness add-ons | manual GitHub Actions job installs MatPortal values with public smoke-compatible runtime images and runs deep smoke including add-on HTTP checks |
| Disposable Kind clean (Linux) | `docs/tutorial-kind-linux.md`, `values/profiles/kind-local.yaml` | Linux Docker/Kind cluster, pinned local-path storage, clean chart rollout, manual port-forwards, and application checks pass |
| Disposable Kind clean (Windows) | `docs/tutorial-kind-windows.md`, `values/profiles/kind-local.yaml` | PowerShell Kind guide derived from Linux run; reviewed but not live-tested on Windows |
| Single-node k3s clean | `docs/tutorial-k3s-laptop-server.md` | clean OntoPortal installs, API/UI roll out, `scripts/smoke.sh` passes; k3s smoke passed, native k3s still pending |
| Single-node k3s MatPortal | MatPortal profile plus site overlay | MatPortal API/UI roll out, Matomo/FAIRness optional pods behave as expected |
| Compose clean | generated `docker-compose.ontoportal-clean.yml` | `docker compose config` passes; optional container start works on a dev host |
| Compose MatPortal | generated `docker-compose.matportal.yml` | `docker compose config` passes; optional container start works on a dev host |
| Terraform clean | clean tfvars/site values | `terraform fmt -check`, `terraform init -backend=false -lockfile=readonly`, `terraform validate`, and a disposable `plan` pass |
| Terraform add-ons | monitoring/logging/security flags | CRD/platform add-ons install before dependent overlays |
| HA cluster | `docs/high-availability.md` | node drain, pod kill, ingress failover, DB/search/RDF failover are proven |
| Backup/restore | `docs/backup-restic.md` | Restic/VolSync/Velero restore into a new namespace succeeds |

## Required static tests

```bash
python3 -m py_compile scripts/*.py
make validate
make validate-generated
# Optional; requires Docker daemon.
make compose-config
git diff --check
```

## Required Helm tests

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
helm template ontoportal-hpa chart/ontoportal --namespace ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/production-recommended.yaml \
  -f values/addons/hpa-autoscaling.yaml >/tmp/ontoportal-hpa.yaml
helm template ontoportal-keda chart/ontoportal --namespace ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/production-recommended.yaml \
  -f values/addons/keda-autoscaling.yaml >/tmp/ontoportal-keda.yaml
helm template ontoportal-vpa chart/ontoportal --namespace ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/production-recommended.yaml \
  -f values/addons/vpa-recommendations.yaml >/tmp/ontoportal-vpa.yaml
```

## Required production-readiness tests

```bash
make production-check PROFILE=ontoportal-clean
make production-check PROFILE=matportal
python3 scripts/production-readiness-check.py \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/production-recommended.yaml \
  -f values/addons/hpa-autoscaling.yaml
python3 scripts/production-readiness-check.py \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/production-recommended.yaml \
  -f values/addons/keda-autoscaling.yaml
python3 scripts/production-readiness-check.py \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/production-recommended.yaml \
  -f values/addons/vpa-recommendations.yaml
python3 scripts/production-readiness-check.py --strict \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/production-recommended.yaml \
  -f values/sites/ontoportal-dev.example.yaml || true
```

Use `--strict` only once site values intentionally address warnings such as image pinning, secret strategy, NetworkPolicy, and RDF-store choice.

## Single-node k3s tutorial rehearsal

For each tutorial rehearsal, capture exact commands and output:

1. Provision a disposable VM or server.
2. Follow `docs/tutorial-k3s-laptop-server.md` without improvising.
3. Record any command that differs from the tutorial.
4. Install clean OntoPortal with an existing Secret and site overlay.
5. Run `SMOKE_DEEP=true scripts/smoke.sh ontoportal ontoportal`.
6. Check ingress with the documented hostnames.
7. Upgrade with the same site values.
8. Roll back one Helm revision.
9. Uninstall/reinstall while preserving PVCs.
10. Update docs for every discrepancy.

## HA test checklist

Run these only after an HA cluster and HA storage/state services exist:

1. Drain one worker node while traffic is active.
2. Kill one API pod and one UI pod.
3. Force a Traefik/ingress pod reschedule.
4. Fail over the database or verify managed database failover.
5. Fail over Redis or verify managed Redis failover.
6. Fail over or restore Solr/RDF store.
7. Confirm PDBs block unsafe evictions when replicas are insufficient.
8. Confirm HPA/KEDA scales only when RWX/externalized state is in place.
9. Confirm recommendation-only VPA publishes sane requests under representative traffic before enabling mutating VPA modes.
10. Verify Alertmanager receives alerts for API/UI downtime and PVC capacity.
11. Run a full namespace restore into a new namespace.

## Backup/restore test checklist

1. Create a Restic repository and record the repository URL without secrets.
2. Back up every PVC or validate VolSync/Velero schedules.
3. Back up database/search/RDF store with application-native tools where available.
4. Restore into a new namespace.
5. Run `SMOKE_DEEP=true scripts/smoke.sh` against the restored release.
6. Validate ontology import/search/annotator/admin flows.
7. Record RPO/RTO, snapshot IDs, and any data loss.

## Application smoke tests still needed

Current smoke tests cover pod/service health: rollout status, pod status, restart totals, API `/`, UI `/` and `/login`, Solr, Redis `PING`, Virtuoso SPARQL `ASK`, mgrep TCP connect, and optional Matomo/FAIRness HTTP services. Playwright covers basic UI rendering, login route reachability, keyboard focus movement, critical same-origin assets, and optional API non-500 checks. Add or manually run tests for:

- admin bootstrap/login with credentials;
- ontology import;
- ontology search result correctness;
- annotator request/response path;
- RDF store query/update path beyond HTTP status;
- cron jobs and scheduled imports beyond process health;
- Matomo analytics setup and tracking path when enabled;
- FAIRness business-level assessment behavior when enabled;
- assistant endpoint and API-key wiring when enabled.

## Failure logging template

Use this template when something fails:

```text
Failure:
Profile/values:
Command:
Observed output:
Root cause:
Fix:
Files changed:
Docs updated:
Regression test added:
Follow-up risk:
```


## Modular environment and provider validation

Run these checks whenever a profile, provider overlay, source-build plan, or environment recipe changes:

```bash
make validate-environments
python3 scripts/image-build-matrix.py -f values/image-builds/ontoportal-source.yaml
python3 scripts/render-environment.py environments/ontoportal-compose-existing.yaml --output /tmp/ontoportal-env
python3 scripts/render-environment.py environments/agroportal-aws-eks.yaml --output /tmp/agroportal-aws --image-tag sha-validated
```

For provider overlays, run static readiness checks before any cluster install:

```bash
python3 scripts/production-readiness-check.py   -f values/profiles/ontoportal-clean.yaml   -f values/profiles/production-recommended.yaml   -f values/cloud/gcp-gke.yaml
```

A complete environment test still requires the provider-specific live path:

- `helm lint` and `helm template` with the rendered values.
- `terraform fmt/init/validate/plan` when Terraform is used.
- Cluster install/upgrade/rollback/uninstall with preserved PVC checks.
- `SMOKE_DEEP=true scripts/smoke.sh`.
- `npm run test:ui` against the deployed UI.
- Provider storage/ingress acceptance evidence.
- HPA/KEDA/VPA checks when the selected overlays enable autoscaling.

Source-build environments also require the manual `build-source-images` workflow or an equivalent local build/scan/push process. The repository-local validation only proves matrix generation and recipe rendering; it does not clone public/private application repositories or verify their Dockerfiles.
