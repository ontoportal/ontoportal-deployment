# ontoportal Helm chart

This chart is profile-driven. Use it with one main profile and zero or more overlays. The short install below is k3s/Traefik-only; for Kind use `../../docs/tutorial-kind-linux.md` (Linux tested) or `../../docs/tutorial-kind-windows.md` (Windows guide) and `values/profiles/kind-local.yaml` instead.

```bash
kubectl create namespace ontoportal || true
helm upgrade --install ontoportal chart/ontoportal \
  --namespace ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/k3s-local.yaml \
  --set global.createNamespace=false
```

Resource names are based on the Helm release, not on MatPortal hard-coded service names.

## Main values sections

- `profile`: profile metadata and whether the profile is MatPortal-specific.
- `global`: namespace, storage class, ingress class, scheduling defaults.
- `images`: images for API, cron, UI, stores, caches, and optional services.
- `persistence`: PVC definitions.
- `api`, `cron`, `ui`: core app workloads.
- `autoscaling`: native HPA or KEDA ScaledObject configuration for horizontally scalable deployments.
- `verticalPodAutoscaling`: VPA resources for recommendation-only or mutating vertical right-sizing.
- `redis`, `solr`, `mgrep`, `store`, `mysql`, `memcached`: dependencies.
- `fairness`, `matomo`, `assistant`, `ontopanel`: optional services.
- `monitoring`: ServiceMonitor toggle.
- `patches`: explicit runtime patch gates.

## Secret contract

Set `secrets.create=false` and `secrets.existingSecret=<name>` for long-lived deployments. The referenced Kubernetes Secret should use these keys:

| Key | Used by | Required when |
| --- | --- | --- |
| `apiKey` | API, UI, cron, FAIRness, assistant | Core API/UI are enabled |
| `adminPassword` | Cron admin bootstrap | `secrets.admin.enabled=true` |
| `mysqlRootPassword` | MySQL and UI database access | `mysql.enabled=true` |
| `storeDbaPassword` | Virtuoso store env | Store password auth is used |
| `storeDavPassword` | Store DAV password env | Store DAV auth is used |
| `matomoDbPassword` | Matomo database | `matomo.enabled=true` |
| `matomoDbRootPassword` | Matomo database root user | `matomo.enabled=true` |
| `mobiSyncInternalToken` | Mobi/assistant integration hooks | Mobi sync integration is enabled |

For disposable dev clusters, leaving values empty lets the chart generate or preserve random values through Helm `lookup`. Do not rely on chart-generated secrets for production.

## Operational constraints

- `global.namespace` should match the Helm release namespace. `scripts/deploy.sh` sets it automatically from the CLI namespace; Terraform/site values should do the same when overriding `namespace`.
- `monitoring.serviceMonitor.enabled=true` requires the Prometheus Operator `ServiceMonitor` CRD to exist before installing this chart.
- `persistence.shared.accessModes` must support `ReadWriteMany` before enabling multiple API/UI replicas, HPAs, or KEDA `ScaledObject`s that scale those workloads.
- `autoscaling.<component>.mode=keda` requires KEDA CRDs/operator before installing this chart; `values/addons/keda-autoscaling.yaml` is an API/UI example overlay.
- `verticalPodAutoscaling.<component>.enabled=true` requires the `autoscaling.k8s.io/v1` VPA CRD/controller before installing this chart; `values/addons/vpa-recommendations.yaml` is a recommendation-only overlay.
- Mutating VPA modes (`Initial`, `Recreate`, `InPlace`, `InPlaceOrRecreate`, `Auto`) must not be combined with CPU/memory-utilization HPA/KEDA for the same workload. Use VPA `Off` to gather recommendations while HPA/KEDA owns replica count.
- Pin image tags or digests in site values before production; profile defaults intentionally keep upstream/dev tags visible. Set `images.<component>.digest` to deploy `repository@sha256:...` instead of `repository:tag`.

## Clean baseline rule

The clean profile must render without MatPortal patches or MatPortal-only services. Add MatPortal behavior in `values/profiles/matportal.yaml`, a values add-on, or a named patch gate.

## Autoscaling

`autoscaling.api`, `autoscaling.ui`, `autoscaling.fairness`, and `autoscaling.assistant` support two horizontal modes:

- `mode: hpa` renders `autoscaling/v2` HorizontalPodAutoscaler resources.
- `mode: keda` renders `keda.sh/v1alpha1` ScaledObject resources.

`verticalPodAutoscaling.<component>` renders `autoscaling.k8s.io/v1` VerticalPodAutoscaler resources for API, cron, UI, Redis, Solr, mgrep, RDF store, MySQL, memcached, FAIRness, Matomo, assistant, and OntoPanel deployments when the matching workload is enabled. Defaults are disabled and recommendation-only (`updateMode: Off`).

CPU and memory horizontal triggers require matching resource requests on the target workload. API/UI scaling beyond one replica requires RWX shared storage or a site-specific external shared-data design. Mutating VPA modes can evict or resize pods, so start with `values/addons/vpa-recommendations.yaml`, review recommendations, then deliberately opt into mutation for suitable workloads. See `docs/autoscaling-keda.md` from the repository root.
