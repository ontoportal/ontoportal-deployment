# k3s deployment tutorial

This tutorial targets an existing **k3s** cluster. It is not the Kind path. For Docker + Kind, use `docs/tutorial-kind-linux.md` (Linux tested) or `docs/tutorial-kind-windows.md` (Windows guide) instead. If you still need to install k3s on a laptop or single server first, start with `docs/tutorial-k3s-laptop-server.md`.

It assumes `kubectl` and `helm` already point at the k3s cluster.

Verify the target before installing:

```bash
kubectl config current-context
kubectl get storageclass
helm version
```

The examples assume k3s `local-path` storage and Traefik ingress. DNS, TLS certificates, backups, and production secret management remain site-specific.

Validation status: clean OntoPortal has been installed and smoke-tested on a disposable k3s cluster using the commands below. Native k3s, MatPortal add-ons, ingress/TLS, rollback, and backup/restore remain to be rehearsed for each target environment; see `docs/validation-evidence.md`.

## 1. Prepare storage and namespace

k3s usually ships with the `local-path` storage class. Confirm it:

```bash
kubectl get storageclass
```

Create a namespace:

```bash
kubectl create namespace ontoportal || true
```

## 2. Create secrets

For a first install you can pass secrets with Helm `--set`, but long-lived installs should use an existing Kubernetes secret or a secret manager.

```bash
kubectl -n ontoportal create secret generic ontoportal-secrets \
  --from-literal=apiKey='replace-with-random-token' \
  --from-literal=adminPassword='replace-with-admin-password' \
  --from-literal=mysqlRootPassword='replace-with-db-password' \
  --from-literal=storeDbaPassword='replace-with-store-dba-password' \
  --from-literal=storeDavPassword='replace-with-store-dav-password' \
  --dry-run=client -o yaml | kubectl apply -f -
```

Then set:

```yaml
secrets:
  create: false
  existingSecret: ontoportal-secrets
```

## 3. Install clean OntoPortal

```bash
helm upgrade --install ontoportal chart/ontoportal \
  --namespace ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/k3s-local.yaml \
  --set global.createNamespace=false \
  --set secrets.create=false \
  --set secrets.existingSecret=ontoportal-secrets
```

## 4. Check rollout

```bash
kubectl -n ontoportal get pods,pvc,svc,ingress
kubectl -n ontoportal logs deploy/ontoportal-api --tail=100
SMOKE_DEEP=true scripts/smoke.sh ontoportal ontoportal
```

## 5. Install MatPortal profile

```bash
kubectl create namespace matportal || true
kubectl -n matportal create secret generic matportal-secrets \
  --from-literal=apiKey='replace-with-random-token' \
  --from-literal=adminPassword='replace-with-admin-password' \
  --from-literal=mysqlRootPassword='replace-with-db-password' \
  --from-literal=storeDbaPassword='replace-with-store-dba-password' \
  --from-literal=storeDavPassword='replace-with-store-dav-password' \
  --from-literal=matomoDbPassword='replace-with-matomo-password' \
  --from-literal=matomoDbRootPassword='replace-with-matomo-root-password' \
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
```

## 6. Ingress

The k3s profile uses Traefik by default. Override hosts in a site-specific values file:

```yaml
ingress:
  hosts:
    ui: matportal.example.org
    api: api.matportal.example.org
  tls:
    enabled: true
    secretName: matportal-tls
```

Install cert-manager, external-dns, or Cloudflare integration separately from this chart.

## 7. Optional ServiceMonitor

Only enable `values/addons/monitoring-servicemonitor.yaml` after Prometheus Operator CRDs exist:

```bash
kubectl api-resources | grep -i '^servicemonitors' || echo 'install kube-prometheus-stack or Prometheus Operator first'
```

## 8. Upgrade

Upgrades must pass the same profile, overlay, site values, namespace, and secret settings used for install. Prefer a checked-in site values file for non-secret settings and an existing Secret for secret values.

```bash
helm diff upgrade ontoportal chart/ontoportal \
  --namespace ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/k3s-local.yaml \
  -f values/sites/ontoportal-dev.example.yaml \
  --set global.createNamespace=false \
  --set secrets.create=false \
  --set secrets.existingSecret=ontoportal-secrets || true

helm upgrade --install ontoportal chart/ontoportal \
  --namespace ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/k3s-local.yaml \
  -f values/sites/ontoportal-dev.example.yaml \
  --set global.createNamespace=false \
  --set secrets.create=false \
  --set secrets.existingSecret=ontoportal-secrets
```

## 9. Rollback

```bash
helm -n ontoportal history ontoportal
helm -n ontoportal rollback ontoportal <revision>
```

## 10. Data backup

For k3s `local-path`, PVC data is stored on the node. Use `scripts/maintenance.sh backup-hint` for local commands. For production, add a CSI driver with snapshots or deploy a backup tool such as Restic/Kopia/Velero.
