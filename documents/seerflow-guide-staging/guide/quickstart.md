# Quickstart — 15 minutes to your first anomaly

This walkthrough takes a clean machine to a working Seerflow run that
flags an anomaly in a sample log dump. Plan for 15 minutes end-to-end.

## Prerequisites

* Python 3.11 or newer
* `uv` (install instructions: <https://docs.astral.sh/uv/getting-started/installation/>)
* ~2 GB of free RAM
* Git (only required for the "from source" install path)

## 1. Install Seerflow

```bash
uv tool install seerflow
seerflow --version
```

If you prefer to run from source — useful for development or for trying a
not-yet-released branch:

```bash
git clone https://github.com/seerflow/seerflow.git
cd seerflow
uv sync
uv run seerflow --version
```

## 2. Grab the sample logs

The sample dump lives next to this page under
[`examples/quickstart/sample-logs.jsonl`](examples/quickstart/sample-logs.jsonl).
It contains 15 nominal API requests followed by a 5-line error burst — the
anomaly we want Seerflow to flag.

```bash
curl -O https://docs.seerflow.dev/examples/quickstart/sample-logs.jsonl
```

Or, if you cloned the docs repo, copy from
`docs/examples/quickstart/sample-logs.jsonl`.

## 3. Run analyse

```bash
seerflow analyze sample-logs.jsonl
```

You should see an alert similar to:

```text
[ALERT] type=ml detector=hst severity=4
        entity=service.checkout-api
        score=0.91 (threshold=0.75)
        body="POST /api/checkout 500 — payment-gateway timeout"
        first_seen=…, last_seen=…
        Reason: 5 consecutive ERROR records exceeded the volume baseline.
```

## 4. Which detector fired and why

The alert came from the **Half-Space Trees content detector**, amplified by
the **volume Holt-Winters detector**:

* HST flagged the new `POST /api/checkout 500` template as content-anomalous
  because it diverges from the GET-heavy 200-status baseline learned in the
  first 15 lines.
* Holt-Winters confirmed a volume spike on the `ERROR` severity track.

Read the per-detector deep dives:

* [Half-Space Trees](detection/half-space-trees.md)
* [Volume Holt-Winters](detection/holt-winters.md)
* [Signal blending and amplification](detection/blending.md)

## 5. Next steps

* [Architecture and pipeline overview](architecture.md) — how analyze fits into the streaming pipeline.
* [Detection deep dives](detection/index.md) — every detector explained with worked examples.
* [Operations guide](operations.md) — running Seerflow as a daemon, configuration, dashboards.
* [Quickstart via Docker compose](examples/quickstart/docker-compose.yml) — same flow, containerised.

If you got stuck, please open an issue at
[github.com/seerflow/seerflow-guide](https://github.com/seerflow/seerflow-guide/issues)
with the `quickstart` label.
