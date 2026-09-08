# Runbook: API pod is not ready

1. Check pod status:

   ```bash
   kubectl -n <namespace> get pods -l app.kubernetes.io/component=api
   kubectl -n <namespace> describe pod <api-pod>
   ```

2. Check dependencies:

   ```bash
   kubectl -n <namespace> get svc,pods | grep -E 'redis|solr|virtuoso|store|mgrep'
   ```

3. Check logs:

   ```bash
   kubectl -n <namespace> logs deploy/<release>-api --tail=200
   ```

4. Common causes:

   - Solr cores not initialized or too slow to start.
   - RDF store not reachable.
   - missing API key secret.
   - image-bundled Ruby dependencies are unavailable.
   - local-path PVC scheduled on a different node from the workload.

5. Recovery:

   - restart the failing dependency;
   - check PVC binding and node scheduling;
   - rollback the Helm release if the failure started after an upgrade.

## Upgrade note

API and cron use the Ruby dependencies baked into their images and fail instead
of installing into `/data/bundle`. mgrep's default supervision clears the
legacy image entrypoint, starts the daemon on the rendered port, and exits
nonzero if it dies. At the configured dictionary path, only the exact
`0\tDUMMY\n` placeholder is replaced from a non-placeholder baked dictionary;
missing usable sources fail clearly, while a genuine nonempty custom dictionary
is retained byte-for-byte. A baked dictionary fixture proves startup wiring
only, not the contents of a user's annotation data.

The local regression scope is `python3 tests/startup_regression.py` plus, when
`STARTUP_DOCKER_TESTS=1`, disposable cached-image containers with `--network
none`; API/cron import checks use read-only `/data`, while full mgrep startup
uses writable temporary `/data`. It does not verify EKS/EFS or remote-cluster
behavior, and it does not pull or repin images.
