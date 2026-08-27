# Maintenance tutorial

The commands below use the k3s/Traefik profile. For Windows Docker Desktop/Kind, use `docs/tutorial-kind-windows.md` and its `kind-local` overlay instead.

## Daily status

```bash
scripts/maintenance.sh status ontoportal ontoportal
```

Look for:

- pods not `Running` or `Completed`
- PVCs stuck in `Pending`
- repeated readiness/liveness failures
- ingress address missing

## Logs

```bash
scripts/maintenance.sh logs ontoportal ontoportal
kubectl -n ontoportal logs deploy/ontoportal-api -f
kubectl -n ontoportal logs deploy/ontoportal-cron -f
kubectl -n ontoportal logs deploy/ontoportal-ui -f
```

## Smoke test

```bash
SMOKE_DEEP=true scripts/smoke.sh ontoportal ontoportal
```

The smoke test port-forwards service endpoints and checks API `/`, UI `/` and `/login`, Solr pings, Redis `PING`, RDF store status, mgrep TCP connectivity, rollout status, pod status, and restart totals. Set `SMOKE_DEEP=false` for only API/UI checks.

## Upgrade checklist

1. Review changed image tags and values.
2. Run `make validate`.
3. Render manifests locally:

   ```bash
   helm template ontoportal chart/ontoportal \
     --namespace ontoportal \
     -f values/profiles/ontoportal-clean.yaml \
     -f values/profiles/k3s-local.yaml > /tmp/ontoportal.yaml
   ```

4. Run `helm diff upgrade` if available.
5. Back up PVCs.
6. Apply with `helm upgrade --install`.
7. Run `SMOKE_DEEP=true scripts/smoke.sh`.

## Restart workloads

```bash
scripts/maintenance.sh restart ontoportal ontoportal
```

## Backups

See `docs/backup-restic.md` for the detailed Restic/VolSync/Velero strategy and restore-drill checklist.

For k3s `local-path`, PVC content lives on the node under `/var/lib/rancher/k3s/storage`. This is acceptable for development, but production should use one of these:

- CSI snapshots
- Restic or Kopia backups to object storage
- Velero with a compatible storage backend
- database-specific dumps for MySQL/Matomo DB when enabled

## Restore outline

1. Stop the release:

   ```bash
   helm -n ontoportal uninstall ontoportal
   ```

2. Restore PVC directories or snapshots.
3. Reinstall the same profile and values.
4. Run smoke tests and ontology-specific checks.

## Image update workflow

1. Change image tags in `chart/ontoportal/values.yaml` or a profile.
2. Run `make validate`.
3. Deploy to a disposable namespace.
4. Run API/UI smoke tests.
5. Promote the same values to stage/production.

## Secret rotation

1. Update the external secret or Kubernetes secret.
2. Restart affected workloads.
3. Check API and UI logs for authentication errors.
4. Keep old API keys temporarily only if clients need a migration window.


## Documentation update requirement

Every operational change must update the documentation in the same change. Examples:

- changed image or startup command: update deployment docs and maintenance docs;
- changed add-on behavior: update security/observability docs;
- changed Terraform flag: update Terraform docs;
- fixed production incident: add or update a runbook;
- changed Compose generator: regenerate Compose and update Compose docs.

See `docs/update-policy.md` for the full policy.
