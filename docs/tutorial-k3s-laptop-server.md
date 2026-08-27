# Single-node k3s tutorial for a laptop or small server

Use this tutorial when you want to run OntoPortal or MatPortal on your own machine with **native k3s** instead of Docker Compose. It does not cover Windows + Docker Desktop/Kind; use `docs/tutorial-kind-windows.md` for that path. This tutorial is meant for development, demos, small internal pilots, and pre-production rehearsals. For public production, read `docs/high-availability.md`, `docs/backup-restic.md`, and `docs/production-readiness.md` before exposing the service.

## 0. What this tutorial does and does not do

This tutorial installs the Helm chart on a single k3s node with:

- k3s default Traefik ingress controller;
- k3s `local-path` storage class;
- Kubernetes Secrets instead of Helm `--set secrets.*` values;
- a site overlay file for hostnames and non-secret settings;
- smoke tests through `kubectl port-forward`.

It does not provide high availability, real TLS automation, production image pinning, restore-tested backups, or externalized databases/search/RDF storage.

Validation status: the clean OntoPortal path in this tutorial has been smoke-tested on a disposable local k3s cluster. Native single-node k3s install, MatPortal add-ons, ingress/TLS, rollback, and backup/restore still need environment-specific rehearsal; see `docs/validation-evidence.md`.

## 1. Hardware and operating system

Recommended minimum for a useful single-node install:

| Use | CPU | RAM | Disk |
| --- | --- | --- | --- |
| Quick clean OntoPortal demo | 4 cores | 12 GiB | 150 GiB SSD |
| MatPortal with Matomo/FAIRness | 8 cores | 24 GiB | 300+ GiB SSD |
| Ontology import/search testing | 8+ cores | 32+ GiB | 500+ GiB SSD |

Use a recent Ubuntu/Debian/Rocky server or a Linux laptop. Docker Desktop Kubernetes is not k3s and is not covered here.

## 2. Install local tools

```bash
sudo apt-get update
sudo apt-get install -y curl git make python3 python3-pip openssl
python3 -m pip install --user pyyaml

# Helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# kubectl if your distro package does not provide a recent one
kubectl version --client=true || true
helm version
```

## 3. Install k3s

For a local test node with default Traefik and `local-path` storage:

```bash
curl -sfL https://get.k3s.io | sudo sh -s - --write-kubeconfig-mode 644
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown "$USER:$USER" ~/.kube/config
kubectl get nodes -o wide
kubectl get storageclass
kubectl -n kube-system get pods
```

If the node is a remote server, copy `/etc/rancher/k3s/k3s.yaml` to your workstation, replace `127.0.0.1` with the server IP or DNS name, and protect the file permissions.

### Optional disposable k3s rehearsal

If you rehearse with a Docker-backed disposable k3s cluster instead of native k3s, use it only as a fast Kubernetes smoke test. In the current Docker environment, the local k3s runner needed the kubelet user-namespace feature gate to avoid a `/dev/kmsg` startup failure:

```bash
k3d cluster create ontoportal-live \
  --agents 0 \
  --timeout 300s \
  --k3s-arg '--kubelet-arg=feature-gates=KubeletInUserNamespace=true@server:*'
```

Then use the generated context for the remaining Helm commands.

## 4. Clone and validate this repository

```bash
git clone git@github.com:matportal/ontoportal-deployment.git
cd ontoportal-deployment
make validate
make validate-generated
helm lint chart/ontoportal -f values/profiles/ontoportal-clean.yaml -f values/profiles/k3s-local.yaml
```

## 5. Pick hostnames

For a laptop, use local hostnames and `/etc/hosts`:

```bash
NODE_IP=$(hostname -I | awk '{print $1}')
echo "$NODE_IP ontoportal.local api.ontoportal.local" | sudo tee -a /etc/hosts
```

For a small server, create DNS records that point to the server IP, for example:

- `ontoportal.example.org` -> server IP
- `api.ontoportal.example.org` -> server IP

You can also validate without DNS by using `scripts/smoke.sh`, which port-forwards services locally.

## 6. Create a site overlay

Copy the example and edit hostnames, URLs, support email, and storage class. Do not put secrets in this file.

```bash
cp values/sites/ontoportal-dev.example.yaml values/sites/my-laptop.yaml
${EDITOR:-nano} values/sites/my-laptop.yaml
```

For the laptop hostnames above, use:

```yaml
global:
  namespace: ontoportal
  storageClassName: local-path
  ingressClassName: traefik

secrets:
  create: false
  existingSecret: ontoportal-secrets

api:
  publicUrl: http://api.ontoportal.local
  restUrlPrefix: http://api.ontoportal.local

ui:
  uiUrl: http://ontoportal.local
  publicApiUrl: http://api.ontoportal.local

ingress:
  enabled: true
  hosts:
    ui: ontoportal.local
    api: api.ontoportal.local
  tls:
    enabled: false

monitoring:
  serviceMonitor:
    enabled: false
```

Keep `monitoring.serviceMonitor.enabled=false` unless the Prometheus Operator CRDs are already installed.

## 7. Create Kubernetes Secrets

Use Kubernetes Secrets for install-time secret values. This avoids leaking passwords through shell history, process lists, and Helm release history.

```bash
kubectl create namespace ontoportal || true
kubectl -n ontoportal create secret generic ontoportal-secrets \
  --from-literal=apiKey="$(openssl rand -base64 36)" \
  --from-literal=adminPassword="$(openssl rand -base64 24)" \
  --from-literal=mysqlRootPassword="$(openssl rand -base64 24)" \
  --from-literal=storeDbaPassword="$(openssl rand -base64 24)" \
  --from-literal=storeDavPassword="$(openssl rand -base64 24)" \
  --dry-run=client -o yaml | kubectl apply -f -
```

For Matomo, add `matomoDbPassword` and `matomoDbRootPassword` too.

## 8. Install clean OntoPortal

```bash
helm upgrade --install ontoportal chart/ontoportal \
  --namespace ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/k3s-local.yaml \
  -f values/sites/my-laptop.yaml \
  --set global.createNamespace=false
```

Watch the rollout:

```bash
kubectl -n ontoportal get pods,pvc,svc,ingress -w
kubectl -n ontoportal rollout status deploy/ontoportal-api --timeout=15m
kubectl -n ontoportal rollout status deploy/ontoportal-ui --timeout=15m
```

## 9. Smoke test

Port-forward smoke test:

```bash
SMOKE_DEEP=true scripts/smoke.sh ontoportal ontoportal
```

Ingress checks:

```bash
curl -fsS http://api.ontoportal.local/
curl -I http://ontoportal.local/
```

If ingress does not answer, check Traefik and service load balancer state:

```bash
kubectl -n kube-system get pods -l app.kubernetes.io/name=traefik
kubectl -n kube-system logs deploy/traefik --tail=100
kubectl -n ontoportal describe ingress ontoportal
```

## 10. Install MatPortal profile on the same node

Use a separate namespace and secret:

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
```

Copy `values/sites/matportal-prod.example.yaml` to a local non-production file and change hosts, TLS, and storage settings. Then install:

```bash
helm upgrade --install matportal chart/ontoportal \
  --namespace matportal \
  -f values/profiles/matportal.yaml \
  -f values/profiles/k3s-local.yaml \
  -f values/addons/matomo.yaml \
  -f values/addons/fairness.yaml \
  -f values/sites/my-matportal.yaml \
  --set global.createNamespace=false

SMOKE_DEEP=true scripts/smoke.sh matportal matportal
```

## 11. Upgrade safely

Always pass the same profile, overlays, site file, namespace, and secret settings used at install time:

```bash
helm diff upgrade ontoportal chart/ontoportal \
  --namespace ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/k3s-local.yaml \
  -f values/sites/my-laptop.yaml \
  --set global.createNamespace=false || true

helm upgrade --install ontoportal chart/ontoportal \
  --namespace ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/k3s-local.yaml \
  -f values/sites/my-laptop.yaml \
  --set global.createNamespace=false
```

Run `SMOKE_DEEP=true scripts/smoke.sh` after every upgrade. Set `SMOKE_DEEP=false` only when you intentionally want a quick API/UI-only check.

## 12. Uninstall without deleting data

```bash
helm -n ontoportal uninstall ontoportal
kubectl -n ontoportal get pvc
```

PVCs remain unless you delete them. To remove everything for a disposable demo:

```bash
kubectl delete namespace ontoportal
# On local-path, confirm host paths before removing any data under /var/lib/rancher/k3s/storage.
```

## 13. Minimum troubleshooting commands

```bash
kubectl -n ontoportal get pods,pvc,svc,ingress
kubectl -n ontoportal describe pod <pod-name>
kubectl -n ontoportal logs deploy/ontoportal-api --tail=200
kubectl -n ontoportal logs deploy/ontoportal-ui --tail=200
kubectl -n ontoportal get events --sort-by=.lastTimestamp | tail -50
```

See `docs/runbooks/api-not-ready.md` and `docs/runbooks/solr-troubleshooting.md` for focused runbooks.
