# Profiles and add-ons

## Profiles

### `values/profiles/ontoportal-clean.yaml`

Use this for a baseline OntoPortal deployment. It intentionally disables MatPortal patches, Matomo, assistant, OntoPanel, and FAIRness by default. The profile uses `agroportal/ontologies_api:master` for both API and cron: upstream `ontoportal_web_ui` requires the `GET /users/:username/ontologies` route present in the selected AgroPortal API, and the matching cron image keeps the runtime compatible with the chart's standalone split Solr cores.

### `values/profiles/agroportal-clean.yaml`

Use this when validating against AgroPortal-style Docker or image conventions. It remains clean: no MatPortal patches or branding.

### `values/profiles/matportal.yaml`

Use this for MatPortal. It enables MatPortal branding and MatPortal-only environment variables. Runtime patches are explicit under `patches.*` so reviewers can see exactly where the deployment diverges from upstream-compatible OntoPortal.

MatPortal is not currently a fully public, reproducible distribution from this repository alone. Some MatPortal runtime images or source repositories may be private, unreleased, or site-specific. A fresh checkout can validate the public chart/profile wiring, but a complete MatPortal deployment needs access to the private images or source repositories, or a site overlay that replaces/disables those components.

### `values/profiles/k3s-local.yaml`

Use this with any main profile on k3s. It assumes the default `local-path` storage class and Traefik ingress class. Do not use it for Kind.

### `values/profiles/kind-local.yaml`

Use this only with the clean profile for the disposable Docker Desktop/Kind path in `docs/tutorial-kind-windows.md`. It uses the `standard` StorageClass from Kind's pinned local-path provisioner, disables ingress, and sizes PVCs for local validation. It is not a production overlay.

### `values/profiles/k3s-ci.yaml`

Use this only with the scheduled/manual `k3s-smoke` GitHub Actions workflow, the manual `matportal-k3s-smoke` workflow, or local disposable k3s smoke rehearsals. It lowers PVC sizes, including Matomo PVCs when enabled, and disables namespace creation/ServiceMonitor assumptions; it is not a production overlay.

### `values/profiles/matportal-k3s-ci.yaml`

Use this only with the manual `matportal-k3s-smoke` workflow. It keeps MatPortal values and add-ons rendered, but swaps MatPortal-specific/private runtime images to public smoke-compatible images and disables the MatPortal API runtime patch so GitHub-hosted CI can validate Kubernetes wiring without image credentials. It does not prove the private MatPortal UI image or FAIRness business logic.

### `values/profiles/docker-compose.yaml`

Use this only when rendering Compose. It lowers resource assumptions and maps services to local-friendly ports.

## Add-ons

Add-ons are opt-in. Some files are OntoPortal chart overlays; others are values for independent platform Helm charts installed through Terraform.

OntoPortal chart overlays can be passed directly to `helm upgrade` with the main chart:

```bash
helm upgrade --install ontoportal chart/ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/k3s-local.yaml \
  -f values/addons/matomo.yaml
```

Current OntoPortal chart overlays:

- `matomo.yaml`
- `fairness.yaml`
- `assistant.yaml`
- `hpa-autoscaling.yaml`
- `keda-autoscaling.yaml` (requires KEDA CRDs/controller first)
- `vpa-recommendations.yaml` (requires VPA CRDs/controller first)
- `monitoring-servicemonitor.yaml` (requires Prometheus Operator CRDs first)

Platform/external chart values consumed by Terraform:

- `monitoring-kube-prometheus-stack.yaml`
- `trivy-operator.yaml`
- `sonarqube-community.yaml`
- `loki-monolithic-dev.yaml`
- `grafana-alloy-loki.yaml`
- `cert-manager.yaml`
- `external-secrets.yaml`
- `kyverno-ha.yaml`
- `keda-operator.yaml`
- `vpa-operator.yaml`
- `velero-provider.example.yaml`


## Cloud provider overlays

Cloud overlays are provider/runtime layers, not standalone profiles:

- `values/cloud/aws-eks.yaml`: AWS Load Balancer Controller/ALB ingress and gp3 RWO storage assumptions.
- `values/cloud/azure-aks.yaml`: AKS CSI storage and Application Gateway Ingress Controller-style annotations.
- `values/cloud/gcp-gke.yaml`: GKE built-in ingress annotation mode and `standard-rwo` storage assumptions.
- `values/cloud/*-rwx-*.example.yaml`: optional RWX storage examples for API/UI horizontal scaling after provider-specific validation.

## Source image build overlays

Use `values/image-builds/*.yaml` when a deployment wants to build application images from Git sources instead of consuming existing registry images:

- `ontoportal-source.yaml` (uses the `agroportal` API branch for `GET /users/:username/ontologies` compatibility with `ontoportal_web_ui` master)
- `bioportal-source.yaml`
- `agroportal-source.yaml`
- `matportal-source.example.yaml` (disabled placeholder; enable only after the referenced MatPortal repositories are available)

These overlays are normally consumed through `scripts/image-build-matrix.py`, `.github/workflows/build-source-images.yml`, and `scripts/render-environment.py`. Built images should be promoted with immutable tags through rendered `image-values.yaml`; keep any digest-based pins in private site overlays outside the rendered environment flow. See `docs/tutorial-custom-profile-source-builds.md` for a profile and source-build walkthrough.

## Environment recipes

`environments/*.yaml` files compose profiles, provider overlays, add-ons, image-build plans, and Terraform/Compose output preferences. They are examples for repeatable targets, not secret-bearing production files.

## Profile policy

A feature belongs in the base chart only when it is a generic OntoPortal feature. A feature belongs in a profile or add-on when it is environment-specific, institution-specific, analytics-specific, or security-platform-specific.

## Version maintenance

Update image tags and chart defaults in one place:

1. Edit `chart/ontoportal/values.yaml` for shared defaults.
2. Override only the deltas in `values/profiles/*.yaml`.
3. Run `make validate`.
4. Render all Compose files with `make compose-all`.
5. Deploy one profile to k3s and run `scripts/smoke.sh`.


## Production overlay

`values/profiles/production-recommended.yaml` is an overlay, not a standalone profile. Combine it with `ontoportal-clean.yaml`, `agroportal-clean.yaml`, or `matportal.yaml`, then add a site-specific file under `values/sites/`.

It adds resource requests/limits, TLS expectation, ServiceMonitor support, and production notes. It deliberately avoids replicas greater than one because the default shared PVC strategy is not safe for horizontal scaling without RWX storage or further application changes.

Example site overlays are included at `values/sites/ontoportal-dev.example.yaml` and `values/sites/matportal-prod.example.yaml`. Copy them before editing; do not commit real secrets.
