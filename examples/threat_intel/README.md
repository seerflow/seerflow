# Threat Intelligence Feed Examples

Reference YAML snippets for wiring the Seerflow TAXII 2.1 feed consumer
(`src/seerflow/threat_intel/`) into a `seerflow.yaml` configuration. Each
file in this directory is a self-contained `threat_intel:` block that can
be copied into the top level of your `seerflow.yaml`.

## Contents

| File | Source | Auth | Notes |
|------|--------|------|-------|
| `alienvault_otx.yaml` | AlienVault OTX (subscribed pulses) | API key (`OTX_API_KEY`) | Hourly poll cadence; uses the `X-OTX-API-KEY` header. |
| `abuse_ch.yaml` | abuse.ch ThreatFox | None (anonymous) | 30-minute cadence; `confidence_floor: 50` filters low-confidence IOCs. |

## Enabling a feed

1. Copy the YAML body of the example into your `seerflow.yaml`. If a
   `threat_intel:` block already exists, merge `feeds:` rather than
   replacing the whole block.
2. Set `enabled: true` at the `threat_intel:` level (the default is
   `false` — see opt-out below).
3. Export any required environment variables (see "Required env vars"
   below) before starting Seerflow. The feed manager reads secrets from
   the environment at startup; missing values mark the feed as failed
   without aborting the pipeline.
4. Restart the Seerflow process. Successful feed startup is logged at
   INFO: `Threat intel: N feed(s) running`.

## Required env vars per feed

| Feed ID | Env vars | How to obtain |
|---------|----------|---------------|
| `alienvault_otx` | `OTX_API_KEY` | Sign up at https://otx.alienvault.com — the API key appears under "Settings → OTX API". |
| `abuse_ch_threatfox` | (none) | The ThreatFox TAXII collection is publicly reachable. |

If a feed is configured for `kind: basic` auth, set both the
`username_env` and `password_env` variables; for `kind: api_key`, set the
`api_key_env` variable. The manager raises `RuntimeError` at startup when
a referenced env var is unset, and logs the affected feed ID at ERROR.

## Smoke test

Seerflow does not currently expose a one-shot CLI flag — the agent runs
until interrupted. Smoke-test by starting the pipeline, waiting one poll
cycle (≤ `poll_interval_s` plus `startup_jitter_s`), then inspecting the
persisted snapshot:

```bash
# Start the agent in one terminal:
OTX_API_KEY=... uv run python -m seerflow start

# After the first poll lands (watch INFO logs for "taxii: poll feed=…"),
# in a second terminal inspect the persisted snapshot bytes
# (SQLite default backend):
sqlite3 ./data/seerflow.sqlite \
  "SELECT key, length(data) FROM model_state WHERE key LIKE 'taxii:%';"
```

You should see two rows per healthy feed: `taxii:snapshot:<id>` and
`taxii:cursor:<id>`. Stop the agent with `Ctrl-C` once you have observed
non-zero snapshot bytes.

The metrics surface lives at `GET /api/v1/stats` — the `taxii` field is
populated whenever `threat_intel.enabled: true`.

## Opt-out

`threat_intel.enabled` defaults to `false` in
`src/seerflow/config.py::ThreatIntelConfig`. Until the operator
explicitly opts in:

- The pipeline never opens an outbound aiohttp session for TAXII.
- No background poll tasks are scheduled.
- The `taxii` field on `/api/v1/stats` is `null`.

To pause an enabled feed without removing its config, set the per-feed
`enabled: false` flag — the manager skips disabled feeds while keeping
the rest of the block intact.

## DNS-rebinding mitigation

Seerflow resolves each feed hostname **once at startup** and pins the
resolved IPv4 address into the `aiohttp.ClientSession`'s resolver
(`seerflow.threat_intel.dns.StaticResolver`). Per-request DNS lookups
are not re-issued — runtime cannot drift from the IP that the startup
SSRF guard validated against `_is_private_ip`.

This means:

- **Geo-DNS / DNS load-balanced TAXII endpoints are not transparently
  followed.** If a feed serves multiple A records and rotates them
  through DNS, Seerflow uses the IP captured at startup until the
  process restarts.
- **Private IPs leaked through DNS at runtime cannot reach the
  pipeline.** A feed whose authoritative DNS later returns
  `169.254.169.254` (cloud IMDS) or `192.168.x.x` cannot be repurposed
  against the host running Seerflow.
- **Opt-out via `allow_private_addresses: true`.** Setting this flag on
  a feed bypasses both the startup SSRF guard *and* the static
  resolver — the feed runs through aiohttp's default resolver. Use
  this only for trusted internal feeds where the operator has audited
  the network path.

### IPv6

The static resolver covers IPv4 only. Feeds whose hostnames resolve
exclusively to IPv6 will fail to start. File a feature request if you
hit this — the SSRF guard already understands IPv6 via
`ipaddress.ip_address`; only the resolver shim needs extending.
