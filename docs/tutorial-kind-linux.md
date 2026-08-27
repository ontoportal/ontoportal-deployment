# Disposable Kind on Linux (tested local path)

Use this tutorial for a clean OntoPortal deployment and validation on Linux
with Docker and Kind. This is the primary and tested Kind path.

For Windows with Docker Desktop and PowerShell, see
`docs/tutorial-kind-windows.md` (derived PowerShell guide, not live-tested on
Windows). For native k3s, see `docs/tutorial-k3s-laptop-server.md`.

This path uses an isolated disposable cluster, the clean profile
(`values/profiles/ontoportal-clean.yaml`), Kind's pinned local-path storage
provisioner (`values/profiles/kind-local.yaml`), and `kubectl port-forward`. It
does not install an ingress controller, expose host ports through Docker, or use
production data. It is not a production deployment.

## 1. Prerequisites

Ensure the following are installed on Linux:

- Docker running Linux containers;
- Kind (v0.29.0 validated with node image `kindest/node:v1.33.1`);
- `kubectl`, `helm` (Helm 3), `git`, `bash`, `curl`, and `openssl`;
- at least 12 GiB of memory available to Docker.

Run all commands from the repository root.

## 2. Create the isolated cluster and storage

Keep this shell session active: it retains the environment variables used by the
subsequent commands. The isolated kubeconfig avoids modifying existing contexts.

```bash
export CLUSTER="ontoportal-kind-$(date -u +%Y%m%d%H%M%S)"
export NAMESPACE="ontoportal"
export RELEASE="ontoportal"
export KUBECONFIG="/tmp/${CLUSTER}.kubeconfig"

kind version
kubectl version --client
helm version
kind create cluster --name "${CLUSTER}" --image kindest/node:v1.33.1 --wait 5m --kubeconfig "${KUBECONFIG}"

# Apply the pinned provisioner shipped in the Kind node image. This is
# idempotent and makes the `standard` StorageClass explicit before Helm runs.
KIND_NODE="$(kind get nodes --name "${CLUSTER}" | head -n 1)"
docker exec "${KIND_NODE}" cat /kind/manifests/default-storage.yaml | kubectl apply -f -

kubectl get nodes -o wide
kubectl get storageclass
kubectl get storageclass standard -o name || { echo "Kind standard StorageClass is missing" >&2; exit 1; }
```

`values/profiles/kind-local.yaml` uses the `standard` StorageClass. Do not
substitute the k3s `local-path` profile. Because Kind runs without an ingress
controller here, ingress is disabled and port-forwards provide access.

## 3. Create the namespace and Secret

The secret keys follow the chart contract. These random values exist only in
this shell session and the disposable cluster; do not print them or commit them.

```bash
API_KEY="$(openssl rand -hex 16)"
ADMIN_PASSWORD="$(openssl rand -hex 16)"
MYSQL_ROOT_PASSWORD="$(openssl rand -hex 16)"
STORE_DBA_PASSWORD="$(openssl rand -hex 16)"
STORE_DAV_PASSWORD="$(openssl rand -hex 16)"

kubectl create namespace "${NAMESPACE}"
kubectl -n "${NAMESPACE}" create secret generic ontoportal-secrets \
  --from-literal="apiKey=${API_KEY}" \
  --from-literal="adminPassword=${ADMIN_PASSWORD}" \
  --from-literal="mysqlRootPassword=${MYSQL_ROOT_PASSWORD}" \
  --from-literal="storeDbaPassword=${STORE_DBA_PASSWORD}" \
  --from-literal="storeDavPassword=${STORE_DAV_PASSWORD}"
```

## 4. Install the clean chart

`kind-local.yaml` configures small PVCs, `standard` storage, local forwarded
URLs for the UI, and `ingress.enabled=false`. The pre-created Secret supplies
required credentials.

```bash
helm upgrade --install "${RELEASE}" ./chart/ontoportal \
  --namespace "${NAMESPACE}" \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/kind-local.yaml \
  --set global.createNamespace=false \
  --set secrets.create=false \
  --set secrets.existingSecret=ontoportal-secrets \
  --timeout 20m \
  --wait

kubectl -n "${NAMESPACE}" get deployments,pods,pvc,svc
kubectl -n "${NAMESPACE}" get deployments -o name | while read -r dep; do
  kubectl -n "${NAMESPACE}" rollout status "${dep}" --timeout=15m
done
```

> **Note on container restarts**: Under transient memory pressure, Virtuoso or
> dependent pods may restart during initialization before stabilizing. The chart
> pins `VIRT_HTTPServer_ServerPort=8890` so Virtuoso recovers cleanly on its
> expected port. All 12 clean-profile deployments reach `1/1` ready.

## 5. Port-forward in two separate terminals

In **Terminal 2**, set the isolated kubeconfig and forward the API:

```bash
export KUBECONFIG="/tmp/<cluster-name>.kubeconfig"
kubectl -n ontoportal port-forward --address 127.0.0.1 svc/ontoportal-api 19393:9393
```

In **Terminal 3**, set the isolated kubeconfig and forward the UI:

```bash
export KUBECONFIG="/tmp/<cluster-name>.kubeconfig"
kubectl -n ontoportal port-forward --address 127.0.0.1 svc/ontoportal-ui 13000:3000
```

Local endpoints:
- UI: `http://127.0.0.1:13000`
- API: `http://127.0.0.1:19393`

## 6. Smoke, import, application, and UI test scripts

In **Terminal 1** (where `${API_KEY}` and `${KUBECONFIG}` are defined):

```bash
export API="http://127.0.0.1:19393"
export UI="http://127.0.0.1:13000"

# Basic reachability checks
curl -fsS "${UI}/login" > /dev/null && echo "UI /login OK"
curl -fsS -H "Authorization: apikey token=${API_KEY}" "${API}/users/admin/ontologies" && echo "API admin ontologies OK"

# Deep infrastructure smoke check
SMOKE_DEEP=true FAIL_ON_RESTARTS=false scripts/smoke.sh "${RELEASE}" "${NAMESPACE}"

# Import and index a smoke test ontology
IMPORT_SMOKE_LOG_DIR=/tmp/ontoportal-kind-import-logs \
  scripts/import-smoke-ontology.sh --env-file /tmp/ontoportal-kind-smoke.env "${RELEASE}" "${NAMESPACE}"

set -a; . /tmp/ontoportal-kind-smoke.env; set +a
export OP_APIKEY="$(kubectl -n "${NAMESPACE}" get secret ontoportal-secrets -o jsonpath='{.data.apiKey}' | base64 --decode)"

# Functional application smoke and UI Playwright tests
SMOKE_REQUIRE_ONTOLOGY=true scripts/app-smoke.sh "${RELEASE}" "${NAMESPACE}"
SMOKE_REQUIRE_ONTOLOGY=true scripts/ui-e2e.sh "${RELEASE}" "${NAMESPACE}"
unset OP_APIKEY
```

## 7. Clean up

Delete the named disposable cluster and temporary kubeconfig:

```bash
kind delete cluster --name "${CLUSTER}" --kubeconfig "${KUBECONFIG}"
rm -f "${KUBECONFIG}" /tmp/ontoportal-kind-smoke.env
```
