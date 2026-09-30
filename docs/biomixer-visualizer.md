# BioMixer replacement visualizer

The [OntoPortal BioMixer Visualizer](https://github.com/ontoportal/biomixer-visualizer) is the maintained replacement for the legacy BioMixer embed. It is a static application packaged as the optional `ontopanel` deployment component.

## Enable it

Add the visualizer overlay to an OntoPortal install:

```bash
helm upgrade --install ontoportal chart/ontoportal \
  --namespace ontoportal \
  -f values/profiles/ontoportal-clean.yaml \
  -f values/profiles/k3s-local.yaml \
  -f values/addons/biomixer-visualizer.yaml
```

The overlay:

- deploys the public MatPortal mirror `ghcr.io/matportal/biomixer-visualizer@sha256:90939ca6b9b7a9a6409c07a38cb60b12f56be6576f6a9bc033fb65df3ffa61df` on port 8000;
- exposes it at `/visualizer` on the UI ingress host;
- sets `ONTOPANEL_VISUALIZER_URL=/visualizer/` in the Web UI container.

By default, the mirror is publicly pullable without authentication and is pinned to the immutable digest above. If overriding `images.ontopanel`, operators must ensure the replacement image is pullable from the deployment nodes; for a private registry, use the existing `global.imagePullSecrets`. Alternatively, run the source-build plan to an accessible registry and override `images.ontopanel` with the resulting image.

Enable the `biomixer_replacement` feature in OntoPortal Web UI after deployment. Until then, Web UI continues to use its existing BioMixer configuration.

For a different public location, override the URL:

```yaml
ui:
  ontopanelVisualizerUrl: https://visualizer.example.org/

ontopanel:
  enabled: false
```

This supports hosting the static application separately without deploying the chart component.

## Build from source

The public source-build plan includes the visualizer repository:

```bash
python3 scripts/image-build-matrix.py \
  -f values/image-builds/ontoportal-source.yaml
```

The chart default is pinned to the immutable MatPortal mirror digest above. Any `images.ontopanel` override should likewise use an immutable image tag or digest.

## Docker Compose

Enable `ontopanel` in a Compose values overlay. The generated visualizer service is published on `ONTOPANEL_PORT` (8000 by default), and Web UI receives its browser-accessible localhost URL. Set `ui.ontopanelVisualizerUrl` when users access Compose through a hostname other than localhost.

## Legacy compatibility

The new repository is a replacement, not a fork or redeployment of the legacy BioMixer source. Disabling the `biomixer_replacement` feature returns Web UI to its pre-replacement path and configuration.
