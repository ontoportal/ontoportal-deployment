# Developer Onboarding: Verification & Testing Guide

## Mission

Take this scaffold from a generated deployment baseline to a tested deployment repository for three supported modes:

1. clean OntoPortal on k3s,
2. MatPortal on k3s with optional Matomo/FAIRness/assistant add-ons,
3. generated Docker Compose from the same values model.

Do not fork the deployment logic into separate hand-maintained Kubernetes and Compose implementations. Kubernetes Helm values are the source of truth; Compose must stay generated.

For local Kind validation, see `docs/tutorial-kind-linux.md` (Linux tested) or `docs/tutorial-kind-windows.md` (Windows PowerShell guide, not live-tested on Windows). The `kind-local` overlay disables ingress and relies on `kubectl port-forward`. The Bash helpers under `scripts/` are for Linux, WSL, or Git Bash and are not claimed to run natively in PowerShell.

## Ground rules for development

- If you change templates, values, Terraform, scripts, images, startup commands, secrets, ports, volumes, probes, or add-on behavior, update the relevant docs in the same commit or pull request.
- If you fix a failure, add the failure mode to a runbook or troubleshooting section.
- If you add a required manual step, document it in the deployment tutorial and maintenance tutorial.
- If you change generated Compose output, rerun the generator and commit the regenerated files.
- If you add an optional add-on, keep it optional and do not enable it in the clean baseline.
- Do not hide MatPortal-specific behavior in shared templates. Put it behind an explicit values gate or in a MatPortal profile/add-on.
- Do not introduce floating image tags into production examples. The default scaffold still uses some upstream-style floating tags for compatibility, but production site values must pin versions or digests.

## First validation pass

Run these checks from the repository root:

```bash
make validate
make validate-generated
make compose-config  # requires Docker daemon
python3 scripts/production-readiness-check.py \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/production-recommended.yaml
python3 scripts/production-readiness-check.py \
  -f values/profiles/matportal.yaml \
  -f values/profiles/production-recommended.yaml
```

Warnings are expected until site-specific values pin images, configure TLS, and choose a production storage class. Errors must be fixed before cluster testing.

If Helm is available, render every main path:

```bash
helm template ontoportal chart/ontoportal \
  --namespace ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/k3s-local.yaml > /tmp/ontoportal-clean.yaml

helm template matportal chart/ontoportal \
  --namespace matportal \
  -f values/profiles/matportal.yaml \
  -f values/profiles/k3s-local.yaml \
  -f values/addons/matomo.yaml \
  -f values/addons/fairness.yaml \
  -f values/addons/monitoring-servicemonitor.yaml > /tmp/matportal.yaml
```

If Docker is available, validate generated Compose:

```bash
make compose-all
for f in compose/generated/docker-compose.*.yml; do
  docker compose -f "$f" config >/dev/null
done
```

## k3s acceptance test sequence

Use a disposable k3s cluster first. Do not start on production data.

1. Install clean OntoPortal:

   ```bash
   kubectl create namespace ontoportal || true
   kubectl -n ontoportal create secret generic ontoportal-secrets \
     --from-literal=apiKey="$(openssl rand -base64 36)" \
     --from-literal=adminPassword="$(openssl rand -base64 24)" \
     --from-literal=mysqlRootPassword="$(openssl rand -base64 24)" \
     --from-literal=storeDbaPassword="$(openssl rand -base64 24)" \
     --from-literal=storeDavPassword="$(openssl rand -base64 24)" \
     --dry-run=client -o yaml | kubectl apply -f -
   helm upgrade --install ontoportal chart/ontoportal \
     --namespace ontoportal \
     -f values/profiles/ontoportal-clean.yaml \
     -f values/profiles/k3s-local.yaml \
     --set global.createNamespace=false \
     --set secrets.create=false \
     --set secrets.existingSecret=ontoportal-secrets
   SMOKE_DEEP=true scripts/smoke.sh ontoportal ontoportal
   ```

2. Check the pod lifecycle:

   ```bash
   kubectl -n ontoportal get pods,pvc,svc,ingress
   kubectl -n ontoportal describe pods
   kubectl -n ontoportal logs deploy/ontoportal-api --tail=200
   kubectl -n ontoportal logs deploy/ontoportal-ui --tail=200
   ```

3. Exercise the important functional paths:

   - API `/` responds.
   - UI `/login` responds.
   - Solr cores exist and can be queried.
   - RDF store responds.
   - mgrep starts and accepts a connection.
   - cron starts without crashing.
   - an ontology import can be run on disposable data.

4. Repeat with MatPortal:

   ```bash
   kubectl create namespace matportal || true
   kubectl -n matportal create secret generic matportal-secrets \
     --from-literal=apiKey="$(openssl rand -base64 36)" \
     --from-literal=adminPassword="$(openssl rand -base64 24)" \
     --from-literal=mysqlRootPassword="$(openssl rand -base64 24)" \
     --from-literal=storeDbaPassword="$(openssl rand -base64 24)" \
     --from-literal=storeDavPassword="$(openssl rand -base64 24)" \
     --from-literal=matomoDbPassword="$(openssl rand -base64 24)" \
     --from-literal=matomoDbRootPassword="$(openssl rand -base64 24)" \
     --dry-run=client -o yaml | kubectl apply -f -
   helm upgrade --install matportal chart/ontoportal \
     --namespace matportal \
     -f values/profiles/matportal.yaml \
     -f values/profiles/k3s-local.yaml \
     -f values/addons/matomo.yaml \
     -f values/addons/fairness.yaml \
     --set global.createNamespace=false \
     --set secrets.create=false \
     --set secrets.existingSecret=matportal-secrets
   SMOKE_DEEP=true scripts/smoke.sh matportal matportal
   ```

5. Validate optional add-ons separately. Add-ons with independent lifecycle should be tested in their own namespaces before coupling them to OntoPortal smoke tests.

## Production add-on acceptance tests

The platform stack should be tested in this order:

1. cert-manager, then an Issuer/ClusterIssuer and a test Certificate.
2. kube-prometheus-stack, then OntoPortal ServiceMonitor discovery.
3. Loki, then Grafana Alloy log ingestion from OntoPortal pods.
4. Trivy Operator, then vulnerability/config reports in the OntoPortal namespace.
5. External Secrets Operator, then an `existingSecret`-based OntoPortal install.
6. Velero or another backup system, then a real restore drill into a new namespace or cluster.
7. Kyverno or another admission policy engine, then policy dry-run/audit before enforce mode.
8. Wazuh, if required, using the official Wazuh Kubernetes deployment and certificate workflow rather than embedding it in the OntoPortal chart.
9. SonarQube, if code quality scanning is required, wired to the source repositories and CI rather than deployed as part of the OntoPortal release.

## Known areas likely to need fixes

- Image entrypoints may differ between upstream OntoPortal, AgroPortal, and MatPortal images. A k3s clean-profile smoke test fixed the current API, UI, and cron startup paths, but AgroPortal and MatPortal image paths still need live confirmation.
- The clean profile uses `agroportal/ontologies_api:master` for both API and cron; keep those matching image/runtime compatibility settings when testing the standalone Solr cores.
- Solr configsets are currently configurable but not automatically generated inside the chart. Confirm whether production should mount generated configsets, run an init job, or move to SolrCloud for newer upstream cron/runtime images.
- Virtuoso is the supported bundled RDF store. For production, validate backup/restore and performance, or use an external RDF store.
- Shared PVC use limits horizontal scaling. Do not enable API/UI HPA or replicas greater than one until shared data is moved to RWX storage or externalized.
- See `docs/testing-plan.md` for smoke-test coverage and application-level test gaps.
- Docker Compose generation should be checked with real images. Some upstream images may expect different paths than the Kubernetes startup scripts.
- Terraform add-ons install generic charts, but cloud-specific values are still required for Velero, Loki production object storage, ingress certificates, DNS, and external secret providers. CI validates Terraform fmt/init/validate, but live plan/apply still needs a target cluster.

## Definition of done for a validation pass

A pass is complete only when:

- `make check-gates` passes.
- `make validate`, `make validate-generated`, Docker-backed `make compose-config`, and Terraform validation pass.
- Helm renders all supported profiles.
- Docker Compose config validates for generated files.
- `docs/tutorial-k3s-laptop-server.md` has been rehearsed on disposable k3s.
- clean OntoPortal starts on disposable k3s.
- MatPortal starts on disposable k3s.
- HA assumptions in `docs/high-availability.md` are tested or explicitly marked pending.
- a Restic/VolSync/Velero backup and restore drill is documented with observed commands and output.
- observability shows API/UI pod logs in Loki and OntoPortal targets in Prometheus.
- every change has matching documentation updates.
