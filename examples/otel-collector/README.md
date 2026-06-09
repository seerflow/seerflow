# OTel Collector Cloud-Ingestion Gateway (reference config)

Reference [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)
**contrib** configuration that ingests cloud log sources — **CloudWatch, GCP
Cloud Logging (via Pub/Sub), Azure Event Hubs, and Kafka** — and forwards them
into Seerflow's existing OTLP receivers. No new Seerflow code is required: the
Collector does the cloud-source fan-in, and Seerflow consumes a single OTLP
stream.

```
AWS CloudWatch ─┐
GCP Pub/Sub ────┤   OTel Collector (contrib)        Seerflow
Azure EventHub ─┤──▶  receivers ▶ batch ▶ otlp  ─────▶ otlp_grpc.py  (:4317)
Kafka ──────────┘                exporter            (or otlp_http.py :4318)
```

Seerflow ingests the **OTLP Logs** signal only (`src/seerflow/receivers/otlp_grpc.py`
on port `4317`; `otlp_http.py` on port `4318` at `POST /v1/logs`). This config
therefore defines a single `logs` pipeline — see
[Logs-only](#logs-only-important) below.

## Files

| File | Purpose |
|------|---------|
| `otel-collector-config.yaml` | The reference Collector config (4 receivers → `otlp` exporter → Seerflow). |
| `docker-compose.yaml` | Local end-to-end smoke path: Collector + Seerflow. |
| `helm/` | Minimal Helm chart to deploy the gateway Collector to Kubernetes — see [Kubernetes (Helm)](#kubernetes-helm). |

The Helm chart and the compose file render the **same** reference
`otel-collector-config.yaml`, so there is a single source of truth for the
Collector configuration across both deployment surfaces.

## Version pin

This config targets **`opentelemetry-collector-contrib` v0.147.0**, pinned in
`docker-compose.yaml` as `otel/opentelemetry-collector-contrib:0.147.0`. The
contrib receivers below evolve quickly and config keys can change between minor
releases, so **always pin a concrete release tag — never `:latest`**. When you
bump the tag, re-verify each receiver's config against that release's component
README before rolling out.

## Receiver stability and caveats

All four cloud receivers ship only in the **contrib** distribution (not the core
Collector), and none is GA. Stability is verified against the v0.147.0 component
READMEs:

| Receiver (type id) | Logs stability (v0.147.0) | Key caveats |
|--------------------|---------------------------|-------------|
| `awscloudwatch` | **alpha** | Poll-based (lists/pulls log groups on `poll_interval`), not push — expect ingestion latency and CloudWatch API cost. Live-data focused, not for historical backfill. |
| `googlecloudpubsub` | **beta** | **Community module** — developed and extensively tested at **Collibra**, but **not officially supported by GCP** (codeowner `@alexvanboxel`). Reads from a Pub/Sub subscription fed by a GCP Logging sink. |
| `azureeventhub` | **beta** | **Checkpoint state is in-memory only** without a storage extension. On restart the receiver resumes from the latest offset, risking missed or reprocessed messages. Wire a `file_storage` extension (`storage: file_storage`) for durable checkpoints — the reference config + compose volume already do this. |
| `kafka` | **beta** | Consumes OTLP-encoded logs; defaults to topic `otlp_logs`, encoding `otlp_proto`. Point upstream producers at the configured topic. |

Treat all four as **beta-or-earlier**: validate in a non-production environment,
monitor the Collector's own telemetry, and pin the version.

## Logs-only (important)

Seerflow registers an OTLP **Logs** service only. The Collector config exports a
single `logs` pipeline to the `otlp` (Seerflow) exporter. **Do not** add
`metrics` or `traces` pipelines that target the same `otlp` exporter — Seerflow
has no metrics/traces receiver and those signals would be silently dropped. (A
structural test, `tests/unit/test_otel_collector_artifacts.py`, enforces this.)

## Enabling a source

For each source you want to ingest:

1. **Provide credentials via environment variables** (never hardcode secrets in
   the YAML):
   - `awscloudwatch` — standard AWS credential chain (`AWS_REGION`, plus an
     instance role / SSO / `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`).
   - `googlecloudpubsub` — `GCP_PROJECT_ID`, `GCP_PUBSUB_SUBSCRIPTION`, and
     `GOOGLE_APPLICATION_CREDENTIALS` (or workload identity).
   - `azureeventhub` — `AZURE_EVENTHUB_CONNECTION_STRING` (include `EntityPath`).
   - `kafka` — `KAFKA_BROKERS`, and `KAFKA_LOGS_TOPIC` if not `otlp_logs`.
2. **Tune the receiver block** in `otel-collector-config.yaml` (log-group
   prefixes, subscription, consumer group, topics).
3. **Remove receivers you do not use** from both the `receivers:` block and the
   `service.pipelines.logs.receivers` list, so the Collector doesn't fail on
   missing credentials at startup.

## End-to-end smoke path

Validates the **gateway → Seerflow** path locally, without any cloud
credentials, by sending a synthetic OTLP log directly through the chain.

1. **Start the stack** (Collector + Seerflow) from the repo root:

   ```bash
   docker compose -f examples/otel-collector/docker-compose.yaml up
   ```

   Seerflow exposes its OTLP gRPC receiver on `localhost:4317`, OTLP HTTP on
   `localhost:4318`, and its health endpoint on `localhost:8080/api/v1/health`.

2. **Confirm Seerflow is healthy:**

   ```bash
   curl -fsS http://localhost:8080/api/v1/health
   ```

3. **Send a synthetic OTLP log.** The simplest path bypasses the cloud
   receivers and posts straight to Seerflow's OTLP **HTTP** receiver
   (`POST /v1/logs`, `otlp_http.py`) to prove ingestion works end to end:

   ```bash
   curl -fsS -X POST http://localhost:4318/v1/logs \
     -H 'Content-Type: application/json' \
     -d '{
       "resourceLogs": [{
         "scopeLogs": [{
           "logRecords": [{
             "timeUnixNano": "1700000000000000000",
             "severityText": "INFO",
             "body": { "stringValue": "seerflow otel gateway smoke test" }
           }]
         }]
       }]
     }'
   ```

   A `200` response with an empty `ExportLogsServiceResponse` confirms Seerflow
   accepted the record.

4. **(Optional) Exercise the Collector** by enabling one receiver (e.g. Kafka
   with a local broker) and producing an `otlp_proto` log to its topic; the
   Collector batches it and forwards it to Seerflow via the `otlp` exporter on
   `:4317`. Watch Seerflow's logs for the `OTLP gRPC receiver` ingestion lines.

5. **Tear down:**

   ```bash
   docker compose -f examples/otel-collector/docker-compose.yaml down -v
   ```

## Kubernetes (Helm)

For a Kubernetes deployment, the `helm/` chart stands up the **gateway
Collector** as a `Deployment` + `ConfigMap` + `Service`. The chart deploys the
gateway **only** — run Seerflow via its own image/release and point the chart's
`seerflow.otlpEndpoint` at it (the gateway forwards logs there via OTLP/gRPC on
`:4317`). The chart renders the same reference `otel-collector-config.yaml` into
a ConfigMap, and pins the same contrib **v0.147.0** image as the compose file.

Install with the defaults, overriding the Seerflow endpoint:

```bash
helm install seerflow-gateway ./examples/otel-collector/helm \
  --set seerflow.otlpEndpoint=seerflow.observability.svc.cluster.local:4317
```

Or supply a values override file (`my-values.yaml`):

```yaml
# my-values.yaml — copy-paste starting point
image:
  # Never use :latest — pin the documented contrib baseline (see Version pin).
  tag: "0.147.0"

seerflow:
  # OTLP/gRPC endpoint of your Seerflow instance (otlp_grpc receiver, :4317).
  otlpEndpoint: "seerflow.observability.svc.cluster.local:4317"
  tlsInsecure: false   # terminate TLS/mTLS in production (see Production notes)

# Per-source cloud credentials come from an EXISTING Kubernetes Secret — never
# inline secret values in the chart. Create it out-of-band, e.g.:
#   kubectl create secret generic seerflow-gateway-creds \
#     --from-literal=AWS_REGION=us-east-1 \
#     --from-literal=GCP_PROJECT_ID=my-project ...
secretRef: "seerflow-gateway-creds"

# Durable Azure Event Hub checkpoints: enable a PVC so the file_storage
# extension survives restarts. Without it, Azure checkpoints are in-memory only
# (see the BETA caveat in Receiver stability and caveats).
persistence:
  enabled: true
  size: 1Gi
```

```bash
helm install seerflow-gateway ./examples/otel-collector/helm -f my-values.yaml
```

After tuning the receivers you want (see [Enabling a source](#enabling-a-source)),
re-package or `helm upgrade` to roll the change. As with the compose path, this
is a **logs-only** Collector — do not add metrics/traces pipelines that target
the Seerflow exporter.

## Production notes

- **TLS.** The reference config uses `tls.insecure: true` for the loopback
  compose network. In production, terminate TLS / mTLS between the Collector and
  Seerflow — remove `insecure`, configure CA/cert/key on the exporter, and pair
  it with Seerflow's receiver-side TLS. See the `otlp_*` TLS keys in the
  repo-root `seerflow.example.yaml`.
- **Durable Azure checkpoints.** Keep the `file_storage` extension enabled and
  back its directory with a persistent volume (the compose file mounts
  `otel-storage`). Without it, Azure Event Hub checkpoints live only in memory.
- **HTTP exporter.** For HTTP-only egress, switch the pipeline to the commented
  `otlphttp` exporter (→ Seerflow `:4318`).
- **Resource limits.** The `memory_limiter` + `batch` processors are tuned
  conservatively; adjust `send_batch_size`/`timeout` and the limiter
  percentages for your throughput.

## See also

- **`docs/operator-guide.md`** (published from the seerflow-guide repo) — the
  canonical operator runbook for this gateway. It cross-links back to the
  FR-006 **receiver caveats** documented above ([Receiver stability and
  caveats](#receiver-stability-and-caveats) — CloudWatch *alpha*; Pub/Sub
  *beta* and Collibra-maintained, not officially supported by GCP; Azure Event
  Hub *beta* with **in-memory checkpoints** unless a `file_storage` extension is
  wired; Kafka *beta*) and to the documented contrib **v0.147.0 version pin**
  ([Version pin](#version-pin)). Treat the operator guide as the entry point;
  this README is the reference for the artifacts it links to.
- `seerflow.example.yaml` (repo root) — Seerflow's own `receivers:` block
  (`otlp_grpc_port: 4317`, `otlp_http_port: 4318`).
- `helm/` — the Kubernetes Helm chart (see [Kubernetes (Helm)](#kubernetes-helm)).
