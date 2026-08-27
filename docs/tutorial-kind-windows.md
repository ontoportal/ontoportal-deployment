# Disposable Kind on Windows (canonical local path)

Use this tutorial for a clean OntoPortal validation on Windows with Docker
Desktop and Kind. It is the canonical Kind path; the k3s tutorials are separate
and should not be combined with it.

This path uses a disposable cluster, the clean profile, Kind's pinned
local-path provisioner, and `kubectl port-forward`. It does not install an
ingress controller, expose a host port through Docker, or use production data.
It is not a production deployment.

## 1. Prerequisites

Install or make available in PowerShell:

- Docker Desktop running Linux containers;
- Kind (the validation below used v0.29.0), kubectl, Helm 3, and Git;
- at least 12 GiB of memory available to Docker Desktop.

Run the commands from this repository's root. If Kind is not installed, use
Kind's official installation instructions; do not use the k3s installer.

## 2. Create the isolated cluster and storage

Keep this PowerShell window open: it holds the generated values used by the
manual API checks later. The timestamp makes the cluster name unique, and the
separate kubeconfig avoids changing another kubectl context.

```powershell
$ErrorActionPreference = "Stop"
$Cluster = "ontoportal-kind-$((Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss'))"
$Namespace = "ontoportal"
$Release = "ontoportal"
$env:KUBECONFIG = Join-Path $env:TEMP "$Cluster.kubeconfig"

kind version
kubectl version --client
helm version
kind create cluster --name $Cluster --image kindest/node:v1.33.1 --wait 5m --kubeconfig $env:KUBECONFIG

# Apply the pinned provisioner shipped in the Kind node image. This is
# idempotent and makes the `standard` StorageClass explicit before Helm runs.
$KindNode = (kind get nodes --name $Cluster | Select-Object -First 1).Trim()
docker exec $KindNode cat /kind/manifests/default-storage.yaml | kubectl apply -f -

kubectl get nodes -o wide
kubectl get storageclass
if (-not (kubectl get storageclass standard -o name)) { throw "Kind standard StorageClass is missing" }
```

The chart's `values/profiles/kind-local.yaml` uses this `standard` class. Do not
substitute the k3s `local-path` profile. Kind has no ingress controller in this
path, so the overlay disables ingress and the checks below use port-forwards.

## 3. Create the namespace and Secret

The key names are part of the chart contract. These values exist only in this
PowerShell process and the disposable cluster; do not print them or commit
them.

```powershell
$apiKey = [guid]::NewGuid().ToString("N")
$adminPassword = [guid]::NewGuid().ToString("N")
$mysqlRootPassword = [guid]::NewGuid().ToString("N")
$storeDbaPassword = [guid]::NewGuid().ToString("N")
$storeDavPassword = [guid]::NewGuid().ToString("N")

kubectl create namespace $Namespace
kubectl -n $Namespace create secret generic ontoportal-secrets `
  --from-literal="apiKey=$apiKey" `
  --from-literal="adminPassword=$adminPassword" `
  --from-literal="mysqlRootPassword=$mysqlRootPassword" `
  --from-literal="storeDbaPassword=$storeDbaPassword" `
  --from-literal="storeDavPassword=$storeDavPassword"
```

## 4. Install the clean chart

This is the one Kind install command. `kind-local.yaml` supplies small PVCs,
`standard` storage, the UI's local forwarded URLs, and `ingress.enabled=false`.
The existing Secret supplies `apiKey`, `adminPassword`,
`mysqlRootPassword`, `storeDbaPassword`, and `storeDavPassword`.

```powershell
helm upgrade --install $Release ./chart/ontoportal `
  --namespace $Namespace `
  -f values/profiles/ontoportal-clean.yaml `
  -f values/profiles/kind-local.yaml `
  --set global.createNamespace=false `
  --set secrets.create=false `
  --set secrets.existingSecret=ontoportal-secrets `
  --timeout 20m `
  --wait

kubectl -n $Namespace get deployments,pods,pvc,svc
kubectl -n $Namespace get deployments -o name | ForEach-Object {
  kubectl -n $Namespace rollout status $_ --timeout=15m
}
$deployments = kubectl -n $Namespace get deployments -o json | ConvertFrom-Json
foreach ($deployment in $deployments.items) {
  if ($deployment.status.readyReplicas -ne $deployment.spec.replicas) {
    throw "Deployment $($deployment.metadata.name) is not ready"
  }
}
"All deployments ready: $($deployments.items.Count)"
```

## 5. Port-forward in two PowerShell windows

In **PowerShell window 2**, set the same isolated kubeconfig and forward the
API. Leave it running:

```powershell
$Cluster = "replace-with-the-cluster-name-from-window-1"
$env:KUBECONFIG = Join-Path $env:TEMP "$Cluster.kubeconfig"
kubectl -n ontoportal port-forward --address 127.0.0.1 svc/ontoportal-api 19393:9393
```

In **PowerShell window 3**, set the same kubeconfig and forward the UI. Leave
it running:

```powershell
$Cluster = "replace-with-the-cluster-name-from-window-1"
$env:KUBECONFIG = Join-Path $env:TEMP "$Cluster.kubeconfig"
kubectl -n ontoportal port-forward --address 127.0.0.1 svc/ontoportal-ui 13000:3000
```

Use `http://127.0.0.1:13000` for the UI and
`http://127.0.0.1:19393` for the API. These are local loopback ports only.

## 6. PowerShell smoke checks

Use **PowerShell window 1**, where `$apiKey` is still defined. `curl.exe` is
used explicitly so PowerShell's `curl` alias cannot change the request.

```powershell
$Api = "http://127.0.0.1:19393"
$Ui = "http://127.0.0.1:13000"
$Headers = @{
  Accept = "application/json"
  Authorization = "apikey token=$apiKey"
}

$login = Invoke-WebRequest -UseBasicParsing -Uri "$Ui/login"
if ($login.StatusCode -ne 200) { throw "UI /login returned $($login.StatusCode)" }
"UI /login HTTP $($login.StatusCode)"

$adminOntologies = Invoke-WebRequest -UseBasicParsing -Headers $Headers -Uri "$Api/users/admin/ontologies"
if ($adminOntologies.StatusCode -ne 200) { throw "admin ontologies returned $($adminOntologies.StatusCode)" }
if (-not $adminOntologies.Content.TrimStart().StartsWith("[")) { throw "admin ontologies is not a JSON array" }
$adminOntologies.Content | ConvertFrom-Json | Out-Null
"GET /users/admin/ontologies HTTP $($adminOntologies.StatusCode) JSON array"
```

## 7. Windows-friendly ontology, mapping, download, search, and annotator checks

The Bash helpers under `scripts/` are not PowerShell commands. The following
manual sequence uses the same API and is suitable for a Windows PowerShell
session. Keep the two port-forward windows running.

Create and upload one disposable ontology:

```powershell
$TtlPath = Join-Path $env:TEMP "ontoportal-kind-smoke.ttl"
$ttl = @'
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://example.org/smoke#> .

<http://example.org/smoke> a owl:Ontology .
:SmokeClass a owl:Class ;
    rdfs:label "Smoke Test Class" ;
    rdfs:comment "A class for smoke testing" .
'@
[System.IO.File]::WriteAllText($TtlPath, $ttl)
$AuthHeader = "Authorization: apikey token=$apiKey"

$createStatus = (& curl.exe -sS -o NUL -w "%{http_code}" `
  -H $AuthHeader -X PUT "$Api/ontologies/SMOKETEST" `
  -F "acronym=SMOKETEST" `
  -F "name=Smoke Test Ontology" `
  -F "hasOntologyLanguage=OWL" `
  -F "administeredBy[]=admin").Trim()
if ($createStatus -notin @("200", "201")) { throw "ontology create returned $createStatus" }

$SubmissionJson = Join-Path $env:TEMP "ontoportal-kind-submission.json"
$uploadStatus = (& curl.exe -sS -o $SubmissionJson -w "%{http_code}" `
  -H $AuthHeader -X POST "$Api/ontologies/SMOKETEST/submissions" `
  -F "name=Smoke Test Ontology" `
  -F "administeredBy=admin" `
  -F "contact[][name]=Admin" `
  -F "contact[][email]=admin@example.org" `
  -F "description=Smoke Test Submission" `
  -F "released=$((Get-Date).ToString('yyyy-MM-dd'))" `
  -F "status=production" `
  -F "hasOntologyLanguage=OWL" `
  -F "URI=http://example.org/smoke" `
  -F "version=1.0.0" `
  -F "file=@$TtlPath;type=text/turtle").Trim()
if ($uploadStatus -ne "201") { throw "ontology upload returned $uploadStatus" }
"ontology create HTTP $createStatus; submission upload HTTP $uploadStatus"
```

Process it on the cron pod. This command can take several minutes on a laptop:

```powershell
$CronPod = (kubectl -n $Namespace get pods `
  -l "app.kubernetes.io/instance=$Release,app.kubernetes.io/component=cron" `
  -o jsonpath='{.items[0].metadata.name}').Trim()
kubectl -n $Namespace exec $CronPod -- bash -lc `
  'if [ -f bin/ncbo_ontology_process ]; then exec bundle exec bin/ncbo_ontology_process "$@"; else exec bundle exec ncbo_ontology_process "$@"; fi' `
  -- -o SMOKETEST -t process_rdf,generate_labels,index_all_data,index_search,process_annotator
kubectl -n $Namespace rollout restart deployment/$Release-mgrep
kubectl -n $Namespace rollout status deployment/$Release-mgrep --timeout=5m
```

Poll until search and annotator return a non-empty collection:

```powershell
function Test-NonEmptyCollection([string]$Content) {
  $body = $Content | ConvertFrom-Json
  if ($body -is [array]) { return @($body).Count -gt 0 }
  if ($null -ne $body.collection) { return @($body.collection).Count -gt 0 }
  if ($null -ne $body.annotations) { return @($body.annotations).Count -gt 0 }
  if ($null -ne $body.annotatedClass) { return $true }
  return $false
}

$processed = $false
for ($i = 1; $i -le 90; $i++) {
  $search = Invoke-WebRequest -UseBasicParsing -Headers $Headers `
    -Uri "$Api/search?q=Smoke%20Test%20Class&ontologies=SMOKETEST"
  $annotator = Invoke-WebRequest -UseBasicParsing -Headers $Headers `
    -Uri "$Api/annotator?text=Smoke%20Test%20Class&ontologies=SMOKETEST&format=json"
  if ((Test-NonEmptyCollection $search.Content) -and (Test-NonEmptyCollection $annotator.Content)) {
    $processed = $true
    break
  }
  Start-Sleep -Seconds 10
}
if (-not $processed) { throw "ontology search/annotator did not become ready" }
"search and annotator ready"
```

Check ontology and submission downloads:

```powershell
$submissions = (Invoke-WebRequest -UseBasicParsing -Headers $Headers `
  -Uri "$Api/ontologies/SMOKETEST/submissions").Content | ConvertFrom-Json
$submissionId = [string]@($submissions)[0].submissionId
if ([string]::IsNullOrWhiteSpace($submissionId)) { throw "submissionId is missing" }

$OntologyDownload = Join-Path $env:TEMP "ontoportal-kind-ontology-download.ttl"
$ontologyDownloadStatus = (& curl.exe -sS -o $OntologyDownload -w "%{http_code}" `
  -H $AuthHeader "$Api/ontologies/SMOKETEST/download").Trim()
$SubmissionDownload = Join-Path $env:TEMP "ontoportal-kind-submission-download.ttl"
$submissionDownloadStatus = (& curl.exe -sS -o $SubmissionDownload -w "%{http_code}" `
  -H $AuthHeader "$Api/ontologies/SMOKETEST/submissions/$submissionId/download").Trim()
if ($ontologyDownloadStatus -ne "200" -or $submissionDownloadStatus -ne "200") {
  throw "download failed: ontology=$ontologyDownloadStatus submission=$submissionDownloadStatus"
}
if ((Get-Item $OntologyDownload).Length -le 0 -or (Get-Item $SubmissionDownload).Length -le 0) {
  throw "downloaded files are empty"
}
"ontology download HTTP $ontologyDownloadStatus; submission download HTTP $submissionDownloadStatus"
```

Exercise mapping CRUD with a disposable external class. The API returns the
mapping id in `id`/`@id`; the URL is escaped before it is used as a path:

```powershell
$MappingPayload = [ordered]@{
  classes = @(
    "http://example.org/smoke#SmokeClass",
    "http://example.org/external#ExternalClass"
  )
  name = "Kind smoke mapping"
  comment = "Kind smoke mapping before patch"
  subject_source_id = "http://example.org/smoke"
  object_source_id = "mappings:external"
  relation = @("http://www.w3.org/2004/02/skos/core#exactMatch")
  creator = "http://data.bioontology.org/users/admin"
} | ConvertTo-Json -Depth 5
$MappingPayloadPath = Join-Path $env:TEMP "ontoportal-kind-mapping.json"
[System.IO.File]::WriteAllText($MappingPayloadPath, $MappingPayload)
$MappingResponse = Join-Path $env:TEMP "ontoportal-kind-mapping-response.json"
$mappingCreateStatus = (& curl.exe -sS -o $MappingResponse -w "%{http_code}" `
  -H $AuthHeader -H "Content-Type: application/json" -X POST "$Api/mappings" `
  --data-binary "@$MappingPayloadPath").Trim()
if ($mappingCreateStatus -ne "201") { throw "mapping create returned $mappingCreateStatus" }
$mapping = Get-Content $MappingResponse -Raw | ConvertFrom-Json
$mappingId = [string]$mapping.id
if ([string]::IsNullOrWhiteSpace($mappingId)) { $mappingId = [string]$mapping.'@id' }
$MappingUrl = "$Api/mappings/$([uri]::EscapeDataString($mappingId))"

$mappingGetStatus = (& curl.exe -sS -o NUL -w "%{http_code}" `
  -H $AuthHeader "$MappingUrl").Trim()
if ($mappingGetStatus -ne "200") { throw "mapping GET returned $mappingGetStatus" }

$PatchPath = Join-Path $env:TEMP "ontoportal-kind-mapping-patch.json"
[System.IO.File]::WriteAllText($PatchPath, '{"comment":"Kind smoke mapping after patch"}')
$mappingPatchStatus = (& curl.exe -sS -o NUL -w "%{http_code}" `
  -H $AuthHeader -H "Content-Type: application/json" -X PATCH "$MappingUrl" `
  --data-binary "@$PatchPath").Trim()
if ($mappingPatchStatus -ne "204") { throw "mapping PATCH returned $mappingPatchStatus" }

$MappingAfterPatch = Join-Path $env:TEMP "ontoportal-kind-mapping-after-patch.json"
$mappingVerifyStatus = (& curl.exe -sS -o $MappingAfterPatch -w "%{http_code}" `
  -H $AuthHeader "$MappingUrl").Trim()
$patchedMapping = Get-Content $MappingAfterPatch -Raw | ConvertFrom-Json
if ($mappingVerifyStatus -ne "200" -or $patchedMapping.process.comment -ne "Kind smoke mapping after patch") {
  throw "mapping patch verification failed"
}

$mappingDeleteStatus = (& curl.exe -sS -o NUL -w "%{http_code}" `
  -H $AuthHeader -X DELETE "$MappingUrl").Trim()
$mappingAfterDeleteStatus = (& curl.exe -sS -o NUL -w "%{http_code}" `
  -H $AuthHeader "$MappingUrl").Trim()
if ($mappingDeleteStatus -ne "204" -or $mappingAfterDeleteStatus -ne "404") {
  throw "mapping delete verification failed: delete=$mappingDeleteStatus after=$mappingAfterDeleteStatus"
}
"mapping CRUD: POST $mappingCreateStatus, GET $mappingGetStatus, PATCH $mappingPatchStatus, DELETE $mappingDeleteStatus, GET-after-delete $mappingAfterDeleteStatus"
```

## 8. Linux/WSL or Git Bash helpers

`smoke.sh`, `import-smoke-ontology.sh`, `app-smoke.sh`, and `ui-e2e.sh` are
Bash scripts. They can be used from WSL or Git Bash, but they are **not claimed
to run natively in PowerShell**. After the PowerShell install above, the
smallest Linux-side functional sequence is:

```bash
export KUBECONFIG=/path/to/the/isolated/$Cluster.kubeconfig
SMOKE_DEEP=true FAIL_ON_RESTARTS=false scripts/smoke.sh ontoportal ontoportal
IMPORT_SMOKE_LOG_DIR=/tmp/ontoportal-kind-import-logs \
  scripts/import-smoke-ontology.sh --env-file /tmp/ontoportal-kind-smoke.env ontoportal ontoportal
set -a; . /tmp/ontoportal-kind-smoke.env; set +a
export OP_APIKEY="$(kubectl -n ontoportal get secret ontoportal-secrets -o jsonpath='{.data.apiKey}' | base64 --decode)"
SMOKE_REQUIRE_ONTOLOGY=true scripts/app-smoke.sh ontoportal ontoportal
SMOKE_REQUIRE_ONTOLOGY=true scripts/ui-e2e.sh ontoportal ontoportal
unset OP_APIKEY
```

The Linux-side import helper covers create/upload/process/search/annotator; the
PowerShell commands above cover those same flows plus mapping CRUD and both
download endpoints.

## 9. Clean up

Delete only the named disposable cluster. This also removes its namespace,
PVCs, generated Secret, and port-forward targets:

```powershell
kind delete cluster --name $Cluster --kubeconfig $env:KUBECONFIG
Remove-Item $env:KUBECONFIG -Force -ErrorAction SilentlyContinue
```
