# System Architecture: Seerflow

**Date:** 2026-03-17
**Architect:** fflores
**Version:** 1.1
**Project Type:** api
**Project Level:** 4
**Status:** Draft

---

## Document Overview

This document defines the system architecture for Seerflow. It provides the technical blueprint for implementation, addressing all 57 functional requirements and 12 non-functional requirements from the PRD.

**Related Documents:**
- Product Requirements Document: docs/prd-seerflow-2026-03-17.md
- Product Brief: docs/product-brief-seerflow-2026-03-17.md
- Research Report: docs/research-architecture-decisions-2026-03-17.md

---

## Executive Summary

Seerflow is architected as a **single-process, pipeline-oriented modular monolith** running on Python 3.12+ with asyncio. All components — ingestion, parsing, detection, correlation, storage, and serving — run in one OS process sharing a single event loop, communicating via in-memory async queues. This eliminates network overhead, simplifies deployment (`pip install seerflow`), and meets the 500MB memory / 10K events/sec / <50ms latency targets.

The architecture is designed around two invariants:
1. **Every event flows through the same pipeline** — ingest → parse → enrich → detect → correlate → store → alert
2. **Every component is a Protocol** — swappable implementations behind Python Protocol interfaces enable SQLite↔PostgreSQL, igraph↔FalkorDB, and future backend swaps without pipeline changes

---

## Architectural Drivers

These NFRs most heavily influence design decisions:

1. **NFR-001: 10K+ events/sec throughput** → Single-process asyncio pipeline with msgspec zero-copy serialization; no inter-process communication overhead
2. **NFR-002: <50ms pipeline latency** → In-memory async queues between stages; no disk I/O on hot path until storage write
3. **NFR-003: <500MB memory** → msgspec.Struct with gc=False (16 bytes saved per event); igraph C-backed graph (32 bytes/edge); bounded queues and LRU model eviction
4. **NFR-005: Install-to-first-alert <5 min** → Zero-config defaults (SQLite, bundled Sigma rules, auto-starting receivers); no external dependencies required
5. **NFR-006: Zero-config first run** → Convention over configuration; sensible defaults for every parameter
6. **NFR-008: Graceful degradation** → Component isolation via try/except per pipeline stage; failure in one stage logs error and passes event through
7. **NFR-012: pip install without C compiler** → All native deps (igraph, msgspec, uvloop, llama-cpp-python) ship pre-built wheels

---

## System Overview

### Architectural Pattern

**Pattern:** Single-Process Pipeline Monolith with Protocol-Based Pluggability

**Rationale:** A microservices architecture would add network latency, deployment complexity, and operational overhead that directly contradicts the target persona (solo SRE on a 4-core server). A monolith with clear module boundaries provides:
- Single `pip install` → single process → single port
- In-memory communication between pipeline stages (~0ms vs ~1-5ms network)
- Shared event loop eliminates serialization between components
- Protocol-based interfaces preserve the option to extract services later (v3/enterprise)

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          seerflow (single process)                      │
│                                                                         │
│  ┌──────────────────────── INGESTION LAYER ──────────────────────────┐  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐               │  │
│  │  │  OTLP   │ │  OTLP   │ │  File   │ │ Syslog  │               │  │
│  │  │  gRPC   │ │  HTTP   │ │ Tailer  │ │ UDP/TCP │               │  │
│  │  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘               │  │
│  │       └───────────┴───────────┴───────────┘                      │  │
│  │                        ▼                                          │  │
│  │              ┌──────────────────┐                                 │  │
│  │              │  Async Queue     │  (bounded, backpressure)        │  │
│  │              └────────┬─────────┘                                 │  │
│  └───────────────────────┼───────────────────────────────────────────┘  │
│                          ▼                                              │
│  ┌──────────────────── PROCESSING PIPELINE ──────────────────────────┐  │
│  │                                                                    │  │
│  │  ┌─────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────┐   │  │
│  │  │ Drain3  │──▶│ Entity   │──▶│ Feature  │──▶│ Detection    │   │  │
│  │  │ Parser  │   │ Extractor│   │ Engineer │   │ Ensemble     │   │  │
│  │  └─────────┘   └──────────┘   └──────────┘   │ ┌──────────┐│   │  │
│  │                                                │ │HST       ││   │  │
│  │  ┌─────────┐   ┌──────────┐                   │ │Holt-Wint.││   │  │
│  │  │ Sigma   │──▶│ Threat   │                   │ │Markov    ││   │  │
│  │  │ Engine  │   │ Intel    │                   │ │CUSUM     ││   │  │
│  │  └─────────┘   │ (Bloom)  │                   │ │DSPOT     ││   │  │
│  │                 └──────────┘                   │ │UEBA      ││   │  │
│  │                                                │ └──────────┘│   │  │
│  │                                                └──────┬───────┘   │  │
│  └───────────────────────────────────────────────────────┼───────────┘  │
│                          ▼                               ▼              │
│  ┌──────────────────── CORRELATION ENGINE ───────────────────────────┐  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐       │  │
│  │  │ Entity Graph │  │ Temporal     │  │ YAML Correlation │       │  │
│  │  │ (igraph)     │  │ Windows      │  │ Rule Evaluator   │       │  │
│  │  └──────────────┘  └──────────────┘  └──────────────────┘       │  │
│  └───────────────────────────────┬───────────────────────────────────┘  │
│                                  ▼                                      │
│  ┌─────────────── OUTPUT LAYER ──────────────────────────────────────┐  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐   │  │
│  │  │ Storage  │  │ Alert    │  │ Feedback │  │ FastAPI +      │   │  │
│  │  │ Writer   │  │ Router   │  │ Loop     │  │ React Dashboard│   │  │
│  │  │(Protocol)│  │(webhooks)│  │(TP/FP)   │  │ + WebSocket    │   │  │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌─────────────── STORAGE LAYER (Protocol-based) ────────────────────┐  │
│  │  ┌──────────────┐              ┌──────────────┐                   │  │
│  │  │   SQLite      │     OR      │  PostgreSQL   │                  │  │
│  │  │  (default)    │             │  (production) │                  │  │
│  │  └──────────────┘              └──────────────┘                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

Every log event traverses this pipeline in order:

```
1. Receiver (OTLP/file/syslog) → raw bytes
2. Async Queue → backpressure boundary
3. Drain3 Parser → SeerflowEvent with template_id
4. Entity Extractor → entity_refs populated (IPs, users, hosts)
5. Entity Resolver → UUID5 canonical IDs
6. Feature Engineer → numeric feature vector for ML
7. Sigma Engine → rule match check (logsource-indexed dispatch)
8. Threat Intel → Bloom filter IoC check
9. Detection Ensemble → anomaly scores (HST, Holt-Winters, Markov, CUSUM)
10. DSPOT Threshold → anomaly flag if score exceeds EVT threshold
11. UEBA Scorer → behavioral deviation score
12. Correlation Engine → entity-temporal window join, YAML rule evaluation
13. Alert Generator → dedup, ATT&CK mapping, risk score
14. Storage Writer → persist event + alert
15. Alert Router → webhooks, PagerDuty, OTLP export
16. WebSocket Broadcast → dashboard live feed
```

Steps 3-12 are the **hot path** — all in-memory, no I/O. Step 14 is the first disk write.

---

## Technology Stack

### Backend Runtime

**Choice:** Python 3.12+ with asyncio + uvloop

**Rationale:** Target language per project requirements. Python 3.12 brings 25% interpreter speedup (PEP 659 specializing adaptive interpreter). uvloop provides 80% of Go's async I/O throughput by replacing the default asyncio event loop with a libuv-based implementation.

**Trade-offs:** Gain: vast ML/data science ecosystem, fast prototyping, solo developer productivity. Lose: raw throughput ceiling vs Go/Rust (mitigated by msgspec C extensions, igraph C core, uvloop C event loop).

### Serialization

**Choice:** msgspec (Struct with frozen=True, gc=False, tag=True)

**Rationale:** 4x faster object creation than dataclasses, 17x faster than Pydantic v2. With gc=False, each SeerflowEvent saves 16 bytes and GC pause drops 75x. MessagePack serialization 13x faster than Pydantic + orjson. This is the single most impactful performance decision for the hot path.

**Trade-offs:** Gain: extreme speed and memory efficiency. Lose: frozen structs require functional update patterns (new object per mutation); less ecosystem support than Pydantic for validation.

### Web Framework

**Choice:** FastAPI + Uvicorn

**Rationale:** Async-native, OpenAPI auto-docs, WebSocket support, lightweight. Uvicorn runs in the same process/event loop as the pipeline — no separate server process needed.

**Trade-offs:** Gain: auto-generated API docs, type-safe request handling, WebSocket native. Lose: slightly more overhead than raw Starlette (negligible for dashboard serving).

### Frontend

**Choice:** React 18 with TypeScript, bundled as static assets

**Rationale:** Largest ecosystem for dashboard components (charting, grids, real-time). Static build bundled into Python package — no Node.js at runtime. Vite for build tooling.

**Key libraries:**
- Recharts or Apache ECharts — anomaly timeline visualization
- React Flow or vis-network — entity graph visualization
- TanStack Table — event/alert data grids
- Zustand — lightweight state management

**Trade-offs:** Gain: rich component ecosystem, TypeScript type safety. Lose: bundle size (~500KB gzipped), build step complexity.

### Entity Graph

**Choice:** igraph (python-igraph)

**Rationale:** Research-validated. 40-250x faster than NetworkX for PageRank, community detection, shortest path. C-backed with Python bindings. 32 bytes/edge + 16 bytes/vertex — 100K entities + 1M edges fits in ~100-150MB. Pre-built wheels on PyPI (no C compiler needed).

**Trade-offs:** Gain: performance, memory efficiency. Lose: less Pythonic API than NetworkX, fewer algorithm implementations (but all Seerflow needs are covered: PageRank, Louvain, shortest path, degree centrality).

### ML / Anomaly Detection

**Choice:** River (HalfSpaceTrees), custom implementations (Holt-Winters, Markov, CUSUM), ads-evt (DSPOT)

**Rationale:** River provides production-quality streaming HST with `learn_one()`/`score_one()` API — true online learning. Holt-Winters and Markov chains are simple enough for custom implementations (avoid large dependency). ads-evt wraps the original KDD'17 SPOT paper with DSPOT drift handling.

**Trade-offs:** Gain: minimal dependencies, streaming-native, no batch training. Lose: fewer algorithms than scikit-learn (but we only need streaming algorithms).

### Sigma Engine

**Choice:** pySigma

**Rationale:** Official Python library from SigmaHQ. Compiles Sigma YAML rules to evaluable expressions. Seerflow adds a logsource-indexed dispatch layer on top for O(rules_per_source) instead of O(total_rules) evaluation.

### Storage

**Choice:** aiosqlite (default) + asyncpg (production), behind Protocol interfaces

**Rationale:** aiosqlite for zero-config first run. asyncpg for production PostgreSQL (fastest Python PostgreSQL driver, pure C implementation). Both behind `LogStore`, `EntityStore`, `ModelStore` Protocols.

### LLM

**Choice:** llama-cpp-python (optional dependency)

**Rationale:** CPU-only inference of quantized GGUF models. 15-25 tokens/sec on 4-core. No GPU required. ~3GB memory overhead. Graceful degradation if not installed.

### Configuration

**Choice:** YAML with `${ENV_VAR:-default}` interpolation, parsed by PyYAML + custom resolver

**Rationale:** YAML is the standard for DevOps tooling (Kubernetes, Docker Compose, Ansible). Env var interpolation handles secrets without hardcoding.

### CLI

**Choice:** Click

**Rationale:** Standard Python CLI framework. Supports subcommands (`seerflow start|status|hunt|export`), auto-generated help, and composable commands.

---

## System Components

### Component 1: Receiver Manager

**Purpose:** Manage lifecycle of all ingestion receivers; multiplex events into unified async queue.

**Responsibilities:**
- Start/stop receivers based on YAML config
- Each receiver runs as an asyncio Task
- All receivers write RawEvent (bytes + metadata) to shared `asyncio.Queue`
- Backpressure: when queue reaches 80% capacity, log warning; at 100%, receivers pause/reject

**Interfaces:**
- `Receiver` Protocol: `async start()`, `async stop()`, `is_healthy() -> bool`
- Implementations: `OtlpGrpcReceiver`, `OtlpHttpReceiver`, `FileTailReceiver`, `SyslogReceiver`

**Dependencies:** None (entry point)

**FRs Addressed:** FR-001, FR-002, FR-003, FR-004, FR-005, FR-006

---

### Component 2: Parser

**Purpose:** Transform raw log bytes into structured SeerflowEvent instances.

**Responsibilities:**
- Drain3 template extraction (template_id, template_str, template_params)
- Entity extraction via regex patterns + OTel resource attributes
- Field normalization: source-specific → canonical SeerflowEvent schema
- Template persistence to storage on configurable interval

**Interfaces:**
- `Parser` Protocol: `parse(raw: RawEvent) -> SeerflowEvent`
- `EntityExtractor` Protocol: `extract(event: SeerflowEvent) -> SeerflowEvent`

**Dependencies:** Drain3 library, storage (for template persistence)

**FRs Addressed:** FR-007, FR-008, FR-009, FR-010

---

### Component 3: Entity Resolver

**Purpose:** Resolve extracted entities into canonical UUID5 identifiers and maintain the entity graph.

**Responsibilities:**
- UUID5 generation: `uuid5(NS_{TYPE}, canonical_value)` for 6 entity types:

  | Type | Raw Forms | Canonical Form | Namespace |
  |------|-----------|---------------|-----------|
  | User | `john.doe`, `CORP\john.doe`, `john.doe@corp.com` | `corp:john.doe` (domain:username, lowercase) | NS_USER |
  | IP | `10.0.1.5`, `::ffff:10.0.1.5`, `010.000.001.005` | `10.0.1.5` (normalized, no leading zeros) | NS_IP |
  | Host | `WEB-SRV-01`, `web-srv-01.corp.local` | `web-srv-01.corp.local` (FQDN, lowercase) | NS_HOST |
  | Process | `nginx:1234` on web-srv-01 | `web-srv-01:1234:1710720000` (host:pid:start_time) | NS_PROC |
  | File | `/etc/passwd`, `C:\Windows\System32\cmd.exe` | `/etc/passwd` (full path, normalized) | NS_FILE |
  | Domain | `cdn-update.xyz`, `www.cdn-update.xyz` | `cdn-update.xyz` (eTLD+1, lowercase) | NS_DOMAIN |

- igraph directed attributed multigraph: add vertices/edges per event with typed edges
- Graph algorithm execution on schedule (PageRank, Louvain, fan-out, ego-graph, betweenness every 5 min)
- Entity timeline indexing for dashboard queries
- Graph serialization to storage for persistence

**Interfaces:**
- `EntityResolver` Protocol: `resolve(event: SeerflowEvent) -> SeerflowEvent`
- `GraphStore` Protocol: `add_event(event)`, `query_entity(uuid) -> Timeline`, `run_pagerank()`, `run_louvain()`

**Dependencies:** igraph, storage

**FRs Addressed:** FR-011, FR-014, FR-015, FR-017

---

### Component 4: Detection Ensemble

**Purpose:** Score each event for anomalies using multiple streaming ML models.

**Responsibilities:**
- Half-Space Trees (content anomaly) — River `HalfSpaceTrees`
- Holt-Winters (volume anomaly) — custom EMA-based, per-source, 1-min buckets, seasonal_period=1440 (daily)
- CUSUM (change detection) — custom cumulative sum
- Markov chains (sequence anomaly) — per-entity transition matrices
- DSPOT auto-thresholds — `ads-evt` biDSPOT per model
- Per-source and per-entity model instances with LRU eviction
- Model state persistence to storage

**Interfaces:**
- `Detector` Protocol: `score(event: SeerflowEvent) -> float`, `learn(event: SeerflowEvent)`, `serialize() -> bytes`, `deserialize(data: bytes)`
- `DetectionEnsemble`: orchestrates all detectors, combines scores

**Internal structure:**
```python
class DetectionEnsemble:
    # Operational Engine (4 detectors)
    hst: dict[str, HalfSpaceTreeDetector]        # per source_type (weight: 0.30)
    holtwinters: dict[str, HoltWintersDetector]   # per source_type (weight: 0.25)
    markov: dict[str, MarkovDetector]             # per entity_uuid, LRU (weight: 0.25)
    cusum: dict[str, CUSUMDetector]               # per source_type (weight: 0.20)
    # Note: Pattern detector (autoencoder+EWC) deferred to v1.1 (PyTorch)

    # Scoring pipeline
    thresholds: dict[str, DSpotThreshold]         # per (detector_type, scope_id)

    # Blended scoring: score → z-normalize → weighted fusion →
    #   signal amplification (2 det=1.5×, 3+=2.0×) → DSPOT threshold → feedback
```

**Blended Scoring Pipeline (6 steps):**
1. Each detector scores independently (no detector sees other scores)
2. Z-normalize raw scores to common scale (mean=0, std=1) per sliding window
3. Weighted fusion: Content×0.30 + Volume×0.25 + Sequence×0.25 + Pattern×0.20
4. Signal amplification: if 2+ detectors flag same entity, multiply (2 det=1.5×, 3+=2.0×)
5. DSPOT EVT threshold: auto-calibrated, no manual tuning
6. Feedback loop: TP/FP adjusts per-detector weights via online learning

**Concept Drift Detection:**
River ADWIN (Adaptive Windowing) monitors each detector's score distribution. When ADWIN detects a statistically significant change in the score stream, it triggers model adaptation — the affected detector's reference window is shortened to prioritize recent data. This prevents stale models from generating increasing false positives after application upgrades, traffic pattern shifts, or seasonal changes.

**Dependencies:** River, ads-evt, storage (for model persistence)

**FRs Addressed:** FR-018, FR-019, FR-020, FR-021, FR-022, FR-023, FR-024, FR-059

---

### Component 5: Sigma Engine

**Purpose:** Evaluate Sigma rules against normalized events for deterministic detection.

**Responsibilities:**
- Load and compile Sigma YAML rules via pySigma
- Logsource-indexed dispatch: `dict[(category, product, service)] -> list[CompiledRule]`
- Per-event evaluation against applicable rules only
- Rule hot-reload via file watcher
- ATT&CK tag extraction from rule metadata

**Interfaces:**
- `SigmaEngine`: `evaluate(event: SeerflowEvent) -> list[SigmaMatch]`
- `SigmaMatch`: dataclass with rule_name, severity, description, attack_tags

**Dependencies:** pySigma, SigmaHQ rules (bundled)

**FRs Addressed:** FR-025, FR-026, FR-027, FR-028

---

### Component 6: Threat Intelligence

**Purpose:** Match events against known indicators of compromise.

**Responsibilities:**
- STIX/TAXII 2.1 feed polling on configurable schedule
- Indicator parsing: extract IPs, domains, hashes, URLs
- Bloom filter construction from indicators
- Per-event IoC matching (IPs, domains from entity extraction)
- IoC alert enrichment with TI context and ATT&CK mapping

**Interfaces:**
- `ThreatIntelStore` Protocol: `refresh()`, `check(value: str) -> TIMatch | None`

**Dependencies:** Bloom filter (built-in or pybloom_live), TAXII client

**FRs Addressed:** FR-049, FR-050, FR-051

---

### Component 7: UEBA Engine

**Purpose:** Compute and score behavioral baselines per entity.

**Responsibilities:**
- Per-entity behavioral baseline: active hours histogram, source IP set, volume EMA, template distribution
- Exponential moving average updates per event
- Deviation scoring: time-of-day, source novelty, volume anomaly, pattern novelty
- Composite UEBA score contributing to risk_score
- Baseline persistence with LRU eviction for inactive entities

**Interfaces:**
- `UEBAEngine`: `score(event: SeerflowEvent) -> float`, `learn(event: SeerflowEvent)`

**Dependencies:** Storage (for baseline persistence)

**FRs Addressed:** FR-052, FR-053

---

### Component 8: Correlation Engine

**Purpose:** Cross-source correlation through entity-temporal window joins and declarative YAML rules.

**Responsibilities:**
- **Three correlation strategies:**
  1. **Entity-Temporal Join** — sliding window per entity, YAML rules join events across sources (default 30m)
  2. **Risk Accumulation** — per-entity risk register with ATT&CK tags, DSPOT threshold on cumulative risk (catches slow-burn attacks)
  3. **Graph-Structural** — community-crossing edges, high-betweenness nodes, sudden fan-out (detects lateral movement)
- Watermark-based late arrival handling
- YAML correlation rule loading and hot-reload
- Kill-chain state machine: track per-entity ATT&CK tactic progression, alert at 3+ tactics
- Correlation alert generation with all contributing events and ATT&CK mapping
- Alert deduplication (same rule + entity + overlapping window)

**Built-in Correlation Rule Patterns (from Technical Architecture v4.0):**

| Scenario | Log Sources | Rule Pattern | ATT&CK |
|----------|------------|-------------|--------|
| Lateral Movement | Auth (failed+success), Network (SMB/RDP), File (sensitive reads) | `IF auth_fail(user,>3) AND auth_success(user) AND network(port∈445,3389) WITHIN 30m` | T1021 |
| Data Exfiltration | VPN (geo anomaly), DNS (new domain), Proxy (large upload) | `IF auth(user,geo_new) AND dns(user,domain_age<7d) AND upload(user,>100MB) WITHIN 60m` | T1048 |
| Credential Abuse | Auth (impossible travel), Endpoint (suspicious exec), Cloud (IAM escalation) | `IF auth(user,impossible_travel) AND process(suspicious_cmd) AND iam(privilege_escalation) WITHIN 30m` | T1078 |

**Interfaces:**
- `CorrelationEngine`: `process(event: SeerflowEvent) -> list[CorrelationAlert]`
- `CorrelationRule`: parsed YAML rule with conditions, entity_type, window, severity, attack_tags

**Internal structure:**
```python
class EntityWindow:
    entity_uuid: str
    events_by_source: dict[str, deque[SeerflowEvent]]  # source_type -> events
    watermark: int  # nanosecond timestamp

class CorrelationEngine:
    windows: dict[str, EntityWindow]  # entity_uuid -> window (LRU bounded)
    rules: list[CorrelationRule]      # hot-reloadable
```

**Dependencies:** Entity Resolver (for UUID lookups)

**FRs Addressed:** FR-012, FR-013, FR-016, FR-043, FR-054, FR-060, FR-061, FR-062

---

### Component 9: Storage Manager

**Purpose:** Unified storage interface with pluggable backends.

**Responsibilities:**
- Event persistence with indexed queries (time, entity, source, severity, template)
- Alert persistence
- Model state persistence (ML models, Drain3 templates, entity baselines)
- Entity timeline queries
- Full-text search (SQLite FTS5 / PostgreSQL tsvector)
- Schema auto-creation and migration

**Interfaces (Protocols):**
```python
class LogStore(Protocol):
    async def write_events(self, events: list[SeerflowEvent]) -> None: ...
    async def query_events(self, filters: EventQuery) -> Page[SeerflowEvent]: ...
    async def search_text(self, query: str, limit: int) -> list[SeerflowEvent]: ...

class AlertStore(Protocol):
    async def write_alert(self, alert: Alert) -> None: ...
    async def query_alerts(self, filters: AlertQuery) -> Page[Alert]: ...
    async def update_feedback(self, alert_id: str, feedback: Feedback) -> None: ...

class ModelStore(Protocol):
    async def save_state(self, key: str, data: bytes) -> None: ...
    async def load_state(self, key: str) -> bytes | None: ...

class EntityStore(Protocol):
    async def get_timeline(self, entity_uuid: str, time_range: TimeRange) -> list[SeerflowEvent]: ...
    async def get_related(self, entity_uuid: str) -> list[EntityRelation]: ...
```

**Implementations:**
- `SqliteBackend` — aiosqlite, WAL mode, FTS5, auto-created in `./data/seerflow.db`
- `PostgresBackend` — asyncpg, connection pooling, tsvector, configurable connection string

**Dependencies:** aiosqlite, asyncpg

**FRs Addressed:** FR-029, FR-030, FR-031, FR-032

---

### Component 10: Alert Router

**Purpose:** Deliver alerts to external systems and collect feedback.

**Responsibilities:**
- Alert deduplication (hash of alert_type + rule_name + entity_uuid)
- Webhook delivery with per-severity routing (Slack, Teams, generic JSON)
- PagerDuty Events API v2 integration (trigger/resolve with dedup_key)
- OTLP alert export (batch, configurable interval)
- TP/FP feedback collection and ML model weight adjustment
- Retry with exponential backoff on delivery failure

**Interfaces:**
- `AlertRouter`: `async route(alert: Alert) -> None`
- `AlertSink` Protocol: `async send(alert: Alert) -> bool`
- Implementations: `SlackSink`, `TeamsSink`, `PagerDutySink`, `OtlpSink`, `GenericWebhookSink`

**Dependencies:** httpx (async HTTP client)

**FRs Addressed:** FR-040, FR-041, FR-042, FR-043, FR-044

---

### Component 11: Web Server & Dashboard

**Purpose:** Serve React dashboard and REST/WebSocket API.

**Responsibilities:**
- FastAPI application mounted at `/api/*`
- Static React asset serving at `/`
- WebSocket endpoint at `/api/ws` for real-time event/alert streaming
- REST endpoints for queries: events, alerts, entities, health, config
- Dashboard: alert feed, anomaly timeline, entity explorer, live stream, ATT&CK matrix
- Widget grid layout with localStorage persistence

**Interfaces:**
- REST API: `/api/v1/events`, `/api/v1/alerts`, `/api/v1/entities`, `/api/v1/health`
- WebSocket: `/api/ws` (JSON messages: events, alerts, system status)

**Dependencies:** FastAPI, Uvicorn, React build artifacts

**FRs Addressed:** FR-033, FR-034, FR-035, FR-036, FR-037, FR-038, FR-039, FR-047

---

### Component 12: CLI

**Purpose:** Command-line interface for all user operations.

**Responsibilities:**
- `seerflow start` — launch process with all components
- `seerflow status` — query running instance health
- `seerflow hunt <query>` — entity search or natural language (with LLM)
- `seerflow export` — dump events/alerts to JSON/CSV
- `seerflow templates list|prune|reset` — Drain3 template management
- `seerflow feedback <alert-id> tp|fp` — alert feedback

**Dependencies:** Click, httpx (for status/hunt/export via health API)

**FRs Addressed:** FR-045, FR-046, FR-048

---

### Component 13: LLM Service (Optional)

**Purpose:** Provide LLM-powered features when a model is configured.

**Responsibilities:**
- Load GGUF model via llama-cpp-python on startup (if configured)
- Alert explanation generation on demand
- Natural language → structured query translation for threat hunting
- Response caching (same alert_id → cached explanation)
- Graceful absence: if not configured, all LLM endpoints return 404 with "LLM not configured" message

**Interfaces:**
- `LLMService` Protocol: `async explain(alert: Alert) -> str`, `async hunt(query: str) -> EventQuery`

**Dependencies:** llama-cpp-python (optional)

**FRs Addressed:** FR-055, FR-056, FR-057

---

## Data Architecture

### Core Data Model

```python
# All frozen msgspec.Structs — immutable, gc-free on hot path

class SeerflowEvent(msgspec.Struct, frozen=True, gc=False, tag=True):
    # Identity
    event_id: uuid.UUID
    timestamp_ns: int           # event time (nanoseconds since epoch)
    observed_ns: int            # pipeline receive time

    # Trace context
    trace_id: str | None = None
    span_id: str | None = None

    # Severity (unified 0-6)
    severity_id: int = 1
    severity_text: str = "Informational"
    otel_severity: int = 9

    # Classification (ECS hierarchy)
    event_kind: str = "event"
    event_category: str = ""
    event_type: str = ""
    event_outcome: str = ""
    event_action: str = ""

    # OCSF numeric taxonomy
    category_uid: int = 0
    class_uid: int = 0
    type_uid: int = 0
    activity_id: int = 0

    # Content
    message: str = ""
    body: Any = None

    # Source tracking
    source_type: str = ""
    source_id: str = ""
    log_source_category: str = ""
    log_source_product: str = ""
    log_source_service: str = ""

    # Drain3 metadata
    template_id: int = -1
    template_str: str = ""
    template_params: tuple[str, ...] = ()

    # Entity references (UUID5 strings)
    entity_refs: tuple[str, ...] = ()
    related_ips: tuple[str, ...] = ()
    related_users: tuple[str, ...] = ()
    related_hosts: tuple[str, ...] = ()
    related_hashes: tuple[str, ...] = ()

    # MITRE ATT&CK
    mitre_tactics: tuple[str, ...] = ()
    mitre_techniques: tuple[str, ...] = ()

    # Scores
    risk_score: float = 0.0
    confidence: float = 1.0
    anomaly_score: float = 0.0

    # Metadata
    attributes: dict[str, Any] = {}
    tags: tuple[str, ...] = ()
    raw_event: str = ""
    resource_attrs: dict[str, str] = {}


class Alert(msgspec.Struct, frozen=True):
    alert_id: str
    alert_type: str             # "ml" | "sigma" | "correlation" | "ueba" | "ioc"
    timestamp_ns: int
    severity_id: int
    rule_name: str
    description: str
    entity_uuid: str
    entity_value: str
    entity_type: str
    contributing_events: tuple[uuid.UUID, ...]
    mitre_tactics: tuple[str, ...] = ()
    mitre_techniques: tuple[str, ...] = ()
    risk_score: float = 0.0
    dedup_key: str = ""
    dedup_count: int = 1
    feedback: str = ""          # "" | "tp" | "fp"


class CorrelationRule(msgspec.Struct, frozen=True):
    name: str
    entity_type: str            # "user" | "ip" | "host"
    window_seconds: int
    sources: tuple[SourceCondition, ...]
    min_sources: int
    alert_severity: int
    mitre_tactics: tuple[str, ...] = ()
    mitre_techniques: tuple[str, ...] = ()
    description: str = ""
```

Note: Hot path structs use `tuple` instead of `list` (frozen, hashable, slightly less memory).

### Database Schema (SQLite / PostgreSQL)

```sql
-- Events table (partitioned by day in PostgreSQL)
CREATE TABLE events (
    event_id        TEXT PRIMARY KEY,       -- UUID as text
    timestamp_ns    INTEGER NOT NULL,
    observed_ns     INTEGER NOT NULL,
    severity_id     INTEGER NOT NULL,
    source_type     TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    template_id     INTEGER,
    message         TEXT,
    raw_event       TEXT,
    entity_refs     TEXT,                   -- JSON array of UUID strings
    attributes      TEXT,                   -- JSON object
    data            BLOB                    -- msgpack-serialized full SeerflowEvent
);

CREATE INDEX idx_events_time ON events (timestamp_ns);
CREATE INDEX idx_events_source ON events (source_type, timestamp_ns);
CREATE INDEX idx_events_severity ON events (severity_id, timestamp_ns);
CREATE INDEX idx_events_template ON events (template_id, timestamp_ns);

-- Entity events junction (for entity timeline queries)
CREATE TABLE entity_events (
    entity_uuid     TEXT NOT NULL,
    event_id        TEXT NOT NULL,
    timestamp_ns    INTEGER NOT NULL,
    PRIMARY KEY (entity_uuid, timestamp_ns, event_id)
);

-- Alerts table
CREATE TABLE alerts (
    alert_id        TEXT PRIMARY KEY,
    alert_type      TEXT NOT NULL,
    timestamp_ns    INTEGER NOT NULL,
    severity_id     INTEGER NOT NULL,
    rule_name       TEXT NOT NULL,
    entity_uuid     TEXT NOT NULL,
    dedup_key       TEXT NOT NULL,
    dedup_count     INTEGER DEFAULT 1,
    feedback        TEXT DEFAULT '',
    data            BLOB                    -- msgpack-serialized full Alert
);

CREATE INDEX idx_alerts_time ON alerts (timestamp_ns);
CREATE INDEX idx_alerts_entity ON alerts (entity_uuid, timestamp_ns);
CREATE INDEX idx_alerts_dedup ON alerts (dedup_key);

-- Model state (key-value store for ML model serialization)
CREATE TABLE model_state (
    key             TEXT PRIMARY KEY,
    data            BLOB NOT NULL,
    updated_at      INTEGER NOT NULL
);

-- Full-text search (SQLite FTS5)
CREATE VIRTUAL TABLE events_fts USING fts5(message, content=events, content_rowid=rowid);
```

### Data Flow: Write Path vs Read Path

**Write path (hot, 10K events/sec):**
```
Event → msgspec.Struct creation → pipeline stages (in-memory) →
batch write to SQLite/PostgreSQL every 100ms or 1000 events (whichever first)
```

Batched writes are critical: SQLite handles ~3.6K individual inserts/sec but ~50K+ in batch mode with prepared statements.

**Read path (warm, dashboard queries):**
```
Dashboard request → FastAPI endpoint → Storage Protocol → SQL query with indexes →
msgpack deserialize → JSON response
```

Read path is async and does not block the write/processing pipeline.

---

## API Design

### REST API

**Base URL:** `http://localhost:8080/api/v1`

**Events:**
- `GET /events` — query events (params: since, until, source, severity, template_id, entity, q, page, limit)
- `GET /events/{event_id}` — get single event

**Alerts:**
- `GET /alerts` — query alerts (params: since, until, type, severity, entity, page, limit)
- `GET /alerts/{alert_id}` — get alert with contributing events
- `POST /alerts/{alert_id}/feedback` — submit TP/FP feedback (body: `{"feedback": "tp|fp", "note": "..."}`)

**Entities:**
- `GET /entities/search?q={value}` — search entities by value (IP, username, hostname)
- `GET /entities/{uuid}` — entity detail (related entities, risk score, baseline)
- `GET /entities/{uuid}/timeline` — entity event timeline (params: since, until, source, page, limit)

**Detection:**
- `GET /sigma/rules` — list loaded Sigma rules with match counts
- `GET /correlation/rules` — list correlation rules
- `GET /models/status` — ML model instance counts and memory usage
- `GET /attack/matrix` — ATT&CK coverage matrix data

**System:**
- `GET /health` — health check (200 OK / 503 degraded)
- `GET /config` — current running configuration (secrets redacted)
- `GET /stats` — throughput, latency percentiles, alert counts

**LLM (optional):**
- `POST /explain/{alert_id}` — generate alert explanation
- `POST /hunt` — natural language search (body: `{"query": "..."}`)

### WebSocket API

**Endpoint:** `ws://localhost:8080/api/ws`

**Message format (JSON):**
```json
{"type": "event", "data": { ... SeerflowEvent fields ... }}
{"type": "alert", "data": { ... Alert fields ... }}
{"type": "status", "data": {"events_per_sec": 5432, "alerts_24h": 17}}
```

**Client can send filter messages:**
```json
{"type": "filter", "sources": ["syslog"], "min_severity": 3}
```

### Authentication

**v1 (Community):** No authentication. Dashboard is accessible on localhost. Users are expected to use network-level access control (firewall, SSH tunnel, VPN).

**v2 (Pro):** JWT-based authentication with SSO/SAML/OIDC integration. RBAC for role-based dashboard access.

---

## Non-Functional Requirements Coverage

### NFR-001: Throughput — 10K+ Events/Sec

**Requirement:** Sustained 10K events/sec on 4-core/4GB server, end-to-end.

**Architecture Solution:**
- Single event loop (uvloop) — no inter-process serialization
- msgspec.Struct (gc=False) — zero GC pressure on hot path
- Batched storage writes (100ms / 1000 events) — amortize I/O
- Logsource-indexed Sigma dispatch — evaluate ~20-50 rules per event, not 500
- LRU-bounded model instances — cap memory regardless of entity count

**Validation:** Benchmark at week 6 with py-spy profiling. Synthetic load generator pushing 10K events/sec for 60 seconds.

### NFR-013: Detection Accuracy — F1 > 0.85 (6mo), > 0.92 (12mo)

**Requirement:** Detection accuracy F1 > 0.85 on LANL Unified Host and Network Dataset at 6 months, improving to F1 > 0.92 by 12 months through feedback loop and model maturation.

**Architecture Solution:**
- Multi-detector ensemble with signal amplification reduces false negatives
- DSPOT EVT thresholds auto-calibrate for <2% false positive rate
- TP/FP feedback loop continuously adjusts per-detector weights
- Sigma rules provide high-precision deterministic baseline while ML matures
- Validated against LANL dataset (1.05B auth events, labeled attack sequences)

---

### NFR-002: Pipeline Latency — Under 50ms

**Requirement:** p95 <50ms from ingestion to alert emission.

**Architecture Solution:**
- All pipeline stages are in-memory function calls — no network, no disk until storage write
- Storage write is async (fire-and-forget to batch writer) — doesn't block pipeline
- Alert routing is async (separate task) — doesn't block pipeline
- Only serialization overhead: msgspec.Struct creation (~0.3μs per object)

**Validation:** Instrument pipeline with `time.perf_counter_ns()` at entry and alert emission. Expose p50/p95/p99 via `/api/v1/stats`.

---

### NFR-003: Memory — Under 500MB Without LLM

**Requirement:** RSS <500MB after 1 hour at 5K events/sec.

**Architecture Solution:**
- SeerflowEvent: ~400 bytes per instance (msgspec.Struct, gc=False)
- Async queue: 100K max × 400B = ~40MB
- igraph: 100K entities + 1M edges = ~100-150MB
- ML models: ~50 per-source models × ~100KB each = ~5MB
- Markov chains: 10K per-entity models (LRU) × ~10KB = ~100MB
- Correlation windows: 10K entities × 1KB avg = ~10MB
- SQLite process memory: ~20-50MB
- **Total estimate: ~350-400MB** — within budget with headroom

**Validation:** Monitor RSS via `/api/v1/health`. Track over 24 hours for leak detection (<10% drift).

---

### NFR-004: Dashboard Performance

**Requirement:** Page load <2s, WebSocket renders at 1K events/sec.

**Architecture Solution:**
- React static assets bundled and gzipped (~500KB)
- WebSocket server-side: throttle to 100 messages/sec to browser (batch 10 events per message)
- REST queries: all indexed, paginated, <500ms target
- No SSR — pure client-side rendering avoids server compute

---

### NFR-005: Install-to-First-Alert Under 5 Minutes

**Architecture Solution:**
- `pip install seerflow` — single package, all dependencies
- `seerflow start` — zero-config: SQLite auto-created, syslog receiver on 514, dashboard on 8080
- Bundled Sigma rules fire on first matching event
- ML detection active after DSPOT calibration (~1000 events, typically 2-5 minutes)

---

### NFR-006: Zero-Config First Run

**Architecture Solution:**
- Every config parameter has a sensible default in code
- `seerflow.yaml` is optional — created only when customization needed
- Default receivers: syslog on 514 (if port available, else warning), file tailing disabled (nothing to tail), OTLP on 4317/4318
- Default storage: SQLite at `./data/seerflow.db` (auto-created)

---

### NFR-007: Security — No Secrets in Default Config

**Architecture Solution:**
- `seerflow.example.yaml` uses `${PAGERDUTY_ROUTING_KEY}` placeholders
- YAML loader resolves `${VAR:-default}` at parse time
- Missing required vars → startup error with clear message
- `.gitignore` template includes `seerflow.yaml`

---

### NFR-008: Graceful Degradation

**Architecture Solution:**
```python
# Each pipeline stage wrapped in error boundary
async def process_event(event: SeerflowEvent) -> SeerflowEvent:
    event = safe_call(parser.parse, event, fallback=event)
    event = safe_call(entity_resolver.resolve, event, fallback=event)
    event = safe_call(detection.score, event, fallback=event)
    event = safe_call(sigma_engine.evaluate, event, fallback=event)
    # ... event always passes through, even if a stage fails
```

- Receiver failure: logged, other receivers continue
- Storage failure: events buffer in memory queue (max 10K, then warn)
- LLM failure: features disabled, core detection unaffected
- ML model error: model reset to fresh state, warning logged

---

### NFR-009: Test Coverage 80%+

**Architecture Solution:**
- Unit tests: each component testable via Protocol interfaces with mock implementations
- Integration tests: SQLite and PostgreSQL backends against identical test suite
- E2E test: synthetic multi-source ingestion → correlated alert verification
- CI: pytest-cov enforces 80% threshold, 90% for critical paths (parser, entity resolver, correlation)

---

### NFR-010: Python 3.12+, Linux-First

**Architecture Solution:**
- CI matrix: Python 3.12, 3.13 on Ubuntu 22.04 + macOS latest
- No `sys.platform`-specific code without guards
- All native deps have manylinux2014 + macosx wheels

---

### NFR-011: Docker Image Under 200MB

**Architecture Solution:**
```dockerfile
# Multi-stage build
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/ .
RUN npm ci && npm run build

FROM python:3.12-slim AS runtime
COPY --from=frontend /app/frontend/dist /app/static
COPY . /app
RUN pip install --no-cache-dir .
USER nobody
EXPOSE 8080 4317 4318 514/udp
HEALTHCHECK CMD curl -f http://localhost:8080/api/v1/health
CMD ["seerflow", "start"]
```

---

### NFR-012: pip Install Without C Compiler

**Architecture Solution:**
- All dependencies verified for pre-built wheel availability on PyPI
- `igraph`: manylinux wheels (C core pre-compiled)
- `msgspec`: manylinux wheels (C extensions pre-compiled)
- `uvloop`: manylinux wheels (libuv pre-compiled)
- `llama-cpp-python`: manylinux wheels (llama.cpp pre-compiled, CPU-only default)
- Verified: `pip install` succeeds on Ubuntu 22.04 minimal without `build-essential`

---

## Security Architecture

### v1 Security Model

Seerflow v1 is a self-hosted tool running on internal infrastructure. Security priorities:

1. **No secrets in code/config** — env var interpolation for all credentials
2. **Input validation** — all receiver inputs validated before pipeline processing
3. **No remote code execution** — Sigma rules and correlation rules are declarative YAML, not executable code
4. **Dashboard on localhost** — no authentication in v1; users secure via network controls
5. **AGPL-3.0** — source code always available, auditable

### Input Validation

- OTLP receivers: protobuf schema validation (malformed messages rejected)
- Syslog receiver: RFC 5424/3164 format validation, max message size limit (64KB)
- File tailer: configurable max line length (default 8KB), binary file detection
- YAML config: schema validation on load, unknown keys logged as warnings
- API inputs: FastAPI/Pydantic request validation on all endpoints

### Future Security (Pro)

- JWT authentication with configurable identity providers
- RBAC: admin, analyst, viewer roles
- TLS for all receivers (OTLP, syslog TCP)
- Audit logging of all user actions

---

## Scalability & Performance

### Scaling Path

**Tier 1 (v1 default, <5K events/sec):**
Single process, SQLite, all-in-one. Runs on 4-core/4GB.

**Tier 1.5 (v1 with PostgreSQL, 5-10K events/sec):**
Single process, PostgreSQL (external), larger server (8-core/8GB). Pipeline unchanged, only storage backend swapped.

**Tier 2 (v2, 10-50K events/sec):**
Multiple Seerflow processes with Redis for shared state. PostgreSQL for storage. Each process handles a subset of log sources. Correlation across processes via shared Redis entity windows.

**Tier 3 (v3/Enterprise, 50K+ events/sec):**
Kafka for ingestion buffering. Multiple Seerflow workers consuming from Kafka partitions. ClickHouse for analytical storage. Kubernetes deployment with horizontal pod autoscaling.

### Performance Optimization Techniques

1. **msgspec zero-copy** — SeerflowEvent creation is the hottest path; msgspec is 4x faster than dataclasses
2. **Batched writes** — group 1000 events or 100ms into single SQL transaction
3. **Prepared statements** — reuse SQL statements across writes
4. **Connection pooling** — asyncpg pool with min=2, max=10 connections
5. **Bloom filter** — O(1) IoC lookup instead of O(n) set membership
6. **Logsource dispatch** — O(rules_per_source) Sigma evaluation instead of O(total_rules)
7. **LRU model eviction** — bound memory regardless of entity count
8. **WebSocket batching** — send 10 events per WS message to dashboard (100 messages/sec × 10 = 1K events/sec display rate)

---

## Reliability & Availability

### v1 Availability

Single-process design means no HA in v1. Reliability via:

- **Graceful degradation** — component failures don't crash process
- **Checkpoint/resume** — file tailer offsets, Drain3 state, ML models persisted to storage
- **Graceful shutdown** — SIGTERM triggers: flush queue → persist all state → close connections → exit
- **Docker restart policy** — `restart: unless-stopped` provides basic auto-recovery
- **Health check** — `/api/v1/health` for Docker/K8s liveness probes

### Monitoring & Alerting

Seerflow monitors itself via the same health endpoint:

- `events_per_sec` — current throughput
- `pipeline_latency_p95_ms` — processing latency
- `queue_depth` — backpressure indicator
- `alert_count_24h` — detection activity
- `model_count` — ML model instances
- `memory_rss_mb` — process memory
- `component_health` — per-component status map
- `template_count` — Drain3 template count
- `template_churn_rate` — new templates/minute

---

## Development Architecture

### Code Organization

```
seerflow/
├── __init__.py
├── __main__.py              # python -m seerflow entry point
├── cli.py                   # Click CLI commands
├── config.py                # YAML config loader with env var interpolation
├── models/
│   ├── event.py             # SeerflowEvent msgspec.Struct
│   ├── alert.py             # Alert, CorrelationRule structs
│   └── query.py             # Query/filter dataclasses
├── receivers/
│   ├── base.py              # Receiver Protocol
│   ├── otlp_grpc.py
│   ├── otlp_http.py
│   ├── file_tailer.py
│   └── syslog.py
├── parsing/
│   ├── drain.py             # Drain3 wrapper
│   ├── entity_extractor.py  # Regex-based entity extraction
│   └── normalizer.py        # Source-specific → SeerflowEvent mapping
├── detection/
│   ├── ensemble.py          # DetectionEnsemble orchestrator
│   ├── hst.py               # Half-Space Trees (River wrapper)
│   ├── holtwinters.py       # Holt-Winters EMA
│   ├── cusum.py             # CUSUM change detection
│   ├── markov.py            # Per-entity Markov chains
│   └── threshold.py         # DSPOT auto-thresholds (ads-evt wrapper)
├── sigma/
│   ├── engine.py            # pySigma evaluation with logsource dispatch
│   └── rules/               # Bundled SigmaHQ rules
├── correlation/
│   ├── engine.py            # Entity-temporal correlation
│   ├── resolver.py          # UUID5 entity resolution
│   ├── graph.py             # igraph entity graph
│   └── rules/               # Bundled correlation YAML rules
├── ueba/
│   ├── baseline.py          # Per-entity behavioral baseline
│   └── scorer.py            # Deviation scoring
├── threat_intel/
│   ├── taxii.py             # STIX/TAXII feed consumer
│   └── bloom.py             # Bloom filter IoC matching
├── storage/
│   ├── protocols.py         # LogStore, AlertStore, ModelStore, EntityStore
│   ├── sqlite.py            # aiosqlite backend
│   └── postgres.py          # asyncpg backend
├── alerting/
│   ├── router.py            # Alert dedup + routing orchestrator
│   ├── sinks/
│   │   ├── webhook.py       # Slack, Teams, generic
│   │   ├── pagerduty.py
│   │   └── otlp.py
│   └── feedback.py          # TP/FP feedback → ML adjustment
├── llm/
│   ├── service.py           # LLMService Protocol + llama-cpp impl
│   ├── explain.py           # Alert explanation prompts
│   └── hunt.py              # NL → structured query translation
├── api/
│   ├── app.py               # FastAPI application factory
│   ├── routes/
│   │   ├── events.py
│   │   ├── alerts.py
│   │   ├── entities.py
│   │   ├── health.py
│   │   ├── detection.py
│   │   └── llm.py
│   └── ws.py                # WebSocket handler
├── pipeline.py              # Main pipeline orchestrator (connects all components)
└── utils/
    ├── time.py              # Nanosecond timestamp utilities
    ├── safe_call.py         # Error boundary wrapper
    └── lru.py               # LRU dict for bounded model/window storage

frontend/                    # React app (separate build)
├── src/
│   ├── components/
│   │   ├── AlertFeed.tsx
│   │   ├── AnomalyTimeline.tsx
│   │   ├── EntityExplorer.tsx
│   │   ├── LiveStream.tsx
│   │   ├── AttackMatrix.tsx
│   │   └── WidgetGrid.tsx
│   ├── hooks/
│   │   └── useWebSocket.ts
│   ├── stores/
│   │   └── dashboardStore.ts
│   └── App.tsx
├── package.json
└── vite.config.ts

tests/
├── unit/
│   ├── test_event.py
│   ├── test_drain.py
│   ├── test_entity_resolver.py
│   ├── test_hst.py
│   ├── test_correlation.py
│   └── ...
├── integration/
│   ├── test_sqlite_backend.py
│   ├── test_postgres_backend.py
│   ├── test_sigma_engine.py
│   └── test_pipeline.py
└── e2e/
    └── test_multi_source_detection.py
```

### Testing Strategy

| Level | Target | Coverage | Tools |
|-------|--------|----------|-------|
| Unit | Individual components via Protocol mocks | 90% for critical paths | pytest, pytest-asyncio |
| Integration | Storage backends, Sigma engine, full pipeline | 80% | pytest, testcontainers (PostgreSQL) |
| E2E | Multi-source ingestion → correlated alert | Key scenarios | pytest, synthetic log generator |
| Performance | Throughput, latency, memory | NFR validation | py-spy, memray, custom benchmarks |

### CI/CD Pipeline

```
Push/PR → GitHub Actions:
  1. Lint (ruff check + ruff format --check)
  2. Type check (mypy --strict)
  3. Unit tests (Python 3.12 + 3.13, Ubuntu + macOS)
  4. Integration tests (PostgreSQL via testcontainers)
  5. Coverage check (pytest-cov, fail if <80%)
  6. Build Docker image
  7. E2E test against Docker image
  8. (Release only) Publish to PyPI + Docker Hub
```

---

## Requirements Traceability

### Functional Requirements Coverage

| FR | Name | Component(s) |
|----|------|-------------|
| FR-001 | OTLP gRPC Receiver | Receiver Manager |
| FR-002 | OTLP HTTP Receiver | Receiver Manager |
| FR-003 | File Tailing | Receiver Manager |
| FR-004 | Syslog Receiver | Receiver Manager |
| FR-005 | Multi-Source Ingestion | Receiver Manager |
| FR-006 | Backpressure | Receiver Manager |
| FR-007 | Drain3 Parsing | Parser |
| FR-008 | Entity Extraction | Parser |
| FR-009 | Field Normalization | Parser |
| FR-010 | Template Persistence | Parser, Storage Manager |
| FR-011 | UUID5 Entity Resolution | Entity Resolver |
| FR-012 | Entity-Temporal Windows | Correlation Engine |
| FR-013 | YAML Correlation Rules | Correlation Engine |
| FR-014 | igraph Entity Graph | Entity Resolver |
| FR-015 | Graph Algorithms | Entity Resolver |
| FR-016 | Correlation Alerts + ATT&CK | Correlation Engine |
| FR-017 | Entity Timeline | Entity Resolver, Storage Manager |
| FR-018 | Half-Space Trees | Detection Ensemble |
| FR-019 | Holt-Winters | Detection Ensemble |
| FR-020 | CUSUM | Detection Ensemble |
| FR-021 | Markov Chains | Detection Ensemble |
| FR-022 | DSPOT Thresholds | Detection Ensemble |
| FR-023 | Per-Source/Entity Models | Detection Ensemble |
| FR-024 | ML Model Persistence | Detection Ensemble, Storage Manager |
| FR-025 | pySigma Evaluation | Sigma Engine |
| FR-026 | SigmaHQ Rules | Sigma Engine |
| FR-027 | Custom Sigma Rules | Sigma Engine |
| FR-028 | Sigma ATT&CK Mapping | Sigma Engine |
| FR-029 | SQLite Backend | Storage Manager |
| FR-030 | PostgreSQL Backend | Storage Manager |
| FR-031 | Backend Switching | Storage Manager |
| FR-032 | Event Queryability | Storage Manager |
| FR-033 | React Dashboard | Web Server |
| FR-034 | Alert Feed Widget | Web Server |
| FR-035 | Anomaly Timeline | Web Server |
| FR-036 | Entity Explorer | Web Server |
| FR-037 | Live Event Stream | Web Server |
| FR-038 | Widget Grid | Web Server |
| FR-039 | ATT&CK Matrix | Web Server |
| FR-040 | Webhook Delivery | Alert Router |
| FR-041 | PagerDuty Integration | Alert Router |
| FR-042 | OTLP Export | Alert Router |
| FR-043 | Alert Deduplication | Alert Router, Correlation Engine |
| FR-044 | TP/FP Feedback | Alert Router, Detection Ensemble |
| FR-045 | CLI Entry Point | CLI |
| FR-046 | YAML Config | Config (cross-cutting) |
| FR-047 | Health Endpoint | Web Server |
| FR-048 | Textual TUI | CLI |
| FR-049 | STIX/TAXII Feeds | Threat Intelligence |
| FR-050 | Bloom Filter IoC | Threat Intelligence |
| FR-051 | IoC Enrichment | Threat Intelligence |
| FR-052 | Per-Entity Baseline | UEBA Engine |
| FR-053 | Behavioral Deviation | UEBA Engine |
| FR-054 | ATT&CK on All Alerts | Correlation Engine, Sigma Engine, UEBA Engine |
| FR-055 | llama-cpp-python | LLM Service |
| FR-056 | Alert Explanations | LLM Service |
| FR-057 | NL Threat Hunting | LLM Service |
| FR-058 | 6 Entity Types (Process, File, Domain) | Entity Resolver |
| FR-059 | Blended Scoring Pipeline | Detection Ensemble |
| FR-060 | Risk Accumulation Correlation | Correlation Engine |
| FR-061 | Graph-Structural Correlation | Correlation Engine, Entity Resolver |
| FR-062 | Kill-Chain State Machine | Correlation Engine |
| FR-063 | Fan-Out, Ego-Graph, Betweenness | Entity Resolver |
| FR-064 | Ollama LLM Backend | LLM Service |
| FR-065 | Cloud API LLM Backend | LLM Service |
| FR-066 | Sigma Rule Suggestion | LLM Service, Sigma Engine |
| FR-067 | Webhooks Receiver | Receiver Manager |
| FR-068 | Dashboard Tech (shadcn/ui, Recharts, D3) | Web Server |

**Coverage: 68/68 FRs assigned (100%)**

### Non-Functional Requirements Coverage

| NFR | Name | Solution |
|-----|------|----------|
| NFR-001 | 10K events/sec | asyncio + uvloop + msgspec + batched writes |
| NFR-002 | <50ms latency | In-memory pipeline, async storage writes |
| NFR-003 | <500MB memory | msgspec gc=False, igraph C-backed, LRU bounds |
| NFR-004 | Dashboard <2s load | Bundled static assets, WebSocket batching |
| NFR-005 | <5 min first alert | Zero-config defaults, bundled Sigma rules |
| NFR-006 | Zero-config | Convention over configuration, optional YAML |
| NFR-007 | No hardcoded secrets | ${ENV_VAR} interpolation |
| NFR-008 | Graceful degradation | Per-stage error boundaries, event passthrough |
| NFR-009 | 80%+ test coverage | Unit + integration + E2E, CI enforcement |
| NFR-010 | Python 3.12+, Linux | CI matrix, wheel verification |
| NFR-011 | Docker <200MB | Multi-stage build, slim base |
| NFR-012 | No C compiler needed | Pre-built wheels for all native deps |
| NFR-013 | F1 > 0.85 (6mo) | Multi-detector ensemble + DSPOT + feedback loop + LANL validation |

**Coverage: 13/13 NFRs addressed (100%)**

---

## Trade-offs & Decision Log

### Decision 1: Single Process vs Microservices

**Choice:** Single process
**Gain:** Zero-config deployment, no network overhead, sub-millisecond inter-component latency, 500MB memory budget achievable
**Lose:** No independent scaling of components, single point of failure, Python GIL limits true parallelism
**Rationale:** Target persona is solo SRE on a 4-core server. Microservices would require Kafka + service mesh + container orchestration — the exact complexity Seerflow aims to eliminate. Single process scales to 10K events/sec; beyond that is v2/v3 territory.

### Decision 2: igraph vs NetworkX

**Choice:** igraph
**Gain:** 40-250x faster graph algorithms, 10x less memory, C-backed performance
**Lose:** Less Pythonic API, fewer algorithms available, requires pre-built wheels
**Rationale:** Research benchmarks show NetworkX is unsuitable at 100K+ entities. igraph provides all needed algorithms (PageRank, Louvain, shortest path) with pre-built wheels. See research report.

### Decision 3: DSPOT vs Static Thresholds

**Choice:** DSPOT (Extreme Value Theory with drift)
**Gain:** Automatic threshold calibration, drift handling, no user tuning needed
**Lose:** ~1000 event calibration period, adds ads-evt dependency
**Rationale:** Static thresholds require per-deployment tuning — violates the "5 minutes to first alert" requirement. DSPOT is self-calibrating. Drift handling prevents threshold staleness in production.

### Decision 4: msgspec vs Pydantic

**Choice:** msgspec.Struct (frozen, gc=False)
**Gain:** 4x faster creation, 17x faster than Pydantic v2, 16 bytes/object GC savings, 13x faster serialization
**Lose:** No built-in validation, frozen requires functional update patterns, smaller ecosystem
**Rationale:** SeerflowEvent is created 10K+ times per second on the hot path. The performance difference is the difference between meeting and missing the 10K events/sec NFR.

### Decision 5: SQLite Default vs PostgreSQL Default

**Choice:** SQLite as default, PostgreSQL as production option
**Gain:** Zero-config first run (no database setup), single-file backup, no external dependency
**Lose:** SQLite caps at ~3.6K individual writes/sec (mitigated by batching), no concurrent write processes
**Rationale:** "Install-to-first-alert in 5 minutes" requires zero external dependencies. PostgreSQL is one config line away for production use.

### Decision 6: AGPL-3.0 License

**Choice:** AGPL-3.0 for Community edition
**Gain:** Strong copyleft prevents cloud providers from offering Seerflow-as-a-service without contributing back; proven by Grafana, Elastic, Redis
**Lose:** Google and some enterprises ban AGPL; creates adoption friction for some organizations
**Rationale:** Target market (mid-market, 50-500 employees) is not affected by AGPL bans. Enterprises with AGPL concerns are exactly the Pro tier customers who get a commercial license.

---

## Open Issues & Risks

1. **igraph incremental update performance** — Need to benchmark `add_vertex()`/`add_edge()` at 10K calls/sec. If too slow, batch graph updates on a timer (every 100ms).
2. **ads-evt Python 3.12+ compatibility** — Untested. If incompatible, fallback to custom DSPOT implementation (~200 lines based on KDD'17 paper).
3. **Drain3 max_clusters tuning** — 1000 default may be too high for memory or too low for diverse log environments. Need empirical data.
4. **React dashboard bundle size** — If exceeds 1MB gzipped, impacts NFR-004. Monitor during development, code-split if needed.
5. **SQLite FTS5 performance** — Full-text search on 1M+ events may be slow. Pagination and time-range filtering mitigate, but need benchmarking.

---

## Assumptions & Constraints

- Single event loop handles all I/O (no multi-process workers in v1)
- All ML models are streaming/online — no batch training, no GPU
- Entity graph fits in memory (bounded by LRU at configured max entities)
- Dashboard serves <10 concurrent browser sessions (not a multi-user web app in v1)
- All native dependencies have pre-built wheels for linux-x86_64 and macosx-arm64
- Python 3.12 is the minimum — no backport to 3.10/3.11

---

## Future Considerations

**v1.1:** Kafka receiver, Redis storage, Helm chart, PyTorch optional (autoencoders), Grafana plugin
**v2:** ClickHouse/DuckDB storage, FalkorDB graph, multi-process workers, kill-chain state machine, alert clustering
**v3/Pro:** Multi-tenancy, SSO/RBAC, HA clustering, horizontal scaling, SOAR integration, Seerflow Cloud

---

## Approval & Sign-off

**Review Status:**
- [x] Technical Lead (Fernando Flores)
- [x] Product Owner (Fernando Flores)
- [ ] Security Architect (N/A — solo project)
- [ ] DevOps Lead (N/A — solo project)

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-17 | fflores | Initial architecture |

---

## Next Steps

### Phase 4: Sprint Planning & Implementation

Run `/sprint-planning` to:
- Break epics into detailed user stories
- Estimate story complexity
- Plan sprint iterations
- Begin implementation following this architectural blueprint

**Key Implementation Principles:**
1. Follow component boundaries defined in this document
2. Implement NFR solutions as specified
3. Use technology stack as defined
4. Follow API contracts exactly
5. Adhere to security and performance guidelines

**Implementation order (recommended):**
1. Models + Config (SeerflowEvent struct, YAML loader) — foundation
2. Storage layer (Protocols + SQLite backend) — persistence
3. Receivers + Parser (syslog + Drain3) — first log ingested
4. Detection ensemble (HST + DSPOT) — first anomaly scored
5. Sigma engine — first deterministic detection
6. Entity resolver + Correlation engine — core differentiator
7. Alert router (webhooks) — alerts reach users
8. API + Dashboard — visual interface
9. UEBA + Threat Intel — enrichment layers
10. LLM integration — explanations and hunting
11. PostgreSQL backend + Docker — production readiness
12. CLI polish + documentation — public launch

---

**This document was created using BMAD Method v6 - Phase 3 (Solutioning)**

*To continue: Run `/workflow-status` to see your progress and next recommended workflow.*

---

## Appendix A: Capacity Planning

| Resource | Tier 1 (SQLite) | Tier 1.5 (PostgreSQL) |
|----------|------------------|-----------------------|
| Events/sec | 5K sustained | 10K sustained |
| CPU cores | 4 | 8 |
| RAM | 4GB (500MB process) | 8GB (500MB + PG) |
| Disk (events) | ~1GB/day at 5K eps | ~2GB/day at 10K eps |
| Disk (DB) | ~500MB/day (compressed) | ~1GB/day |
| Entities | 10-50K | 50-200K |
| Sigma rules | 50-500 | 500-2000 |
| ML models | ~50 per-source + 10K per-entity | same |

## Appendix B: Dependency Matrix

| Package | Version | Purpose | Wheel Available | Size |
|---------|---------|---------|-----------------|------|
| msgspec | >=0.18 | Event serialization | Yes (manylinux) | ~1MB |
| drain3 | >=0.9 | Log template parsing | Yes (pure Python) | <1MB |
| python-igraph | >=0.11 | Entity graph | Yes (manylinux) | ~5MB |
| river | >=0.21 | HalfSpaceTrees | Yes (pure Python) | ~3MB |
| ads-evt | >=0.1 | DSPOT thresholds | TBD | <1MB |
| pySigma | >=0.10 | Sigma rule evaluation | Yes (pure Python) | ~1MB |
| fastapi | >=0.110 | Web framework | Yes (pure Python) | <1MB |
| uvicorn | >=0.29 | ASGI server | Yes (pure Python) | <1MB |
| uvloop | >=0.19 | Fast event loop | Yes (manylinux) | ~2MB |
| aiosqlite | >=0.20 | Async SQLite | Yes (pure Python) | <1MB |
| asyncpg | >=0.29 | Async PostgreSQL | Yes (manylinux) | ~1MB |
| click | >=8.1 | CLI framework | Yes (pure Python) | <1MB |
| httpx | >=0.27 | Async HTTP client | Yes (pure Python) | <1MB |
| pyyaml | >=6.0 | Config parsing | Yes (manylinux) | <1MB |
| llama-cpp-python | >=0.2 | LLM inference (optional) | Yes (manylinux) | ~50MB |

---

## Appendix C: Entity Type Definitions

> Source: `docs/background/Designing Seerflow's event schema and storage backend.md`

Entity types are msgspec.Structs with tagged-union discriminated decoding via `tag_field="entity_type"`.

### UUID5 Namespace Constants

```python
import uuid

NS_USER    = uuid.UUID("a1b2c3d4-0001-0000-0000-000000000001")
NS_IP      = uuid.UUID("a1b2c3d4-0002-0000-0000-000000000002")
NS_HOST    = uuid.UUID("a1b2c3d4-0003-0000-0000-000000000003")
NS_PROCESS = uuid.UUID("a1b2c3d4-0004-0000-0000-000000000004")
NS_FILE    = uuid.UUID("a1b2c3d4-0005-0000-0000-000000000005")
NS_DOMAIN  = uuid.UUID("a1b2c3d4-0006-0000-0000-000000000006")
```

### Entity Structs

```python
class UserEntity(msgspec.Struct, frozen=True, tag="user", tag_field="entity_type"):
    entity_id: UUID
    first_seen: int      # nanoseconds since epoch
    last_seen: int
    username: str
    domain: str | None = None
    email: str | None = None
    sid: str | None = None         # Windows Security Identifier
    uid: int | None = None         # POSIX UID
    groups: tuple[str, ...] = ()
    is_service_account: bool = False
    source_count: int = 1
    confidence: float = 1.0

class IPEntity(msgspec.Struct, frozen=True, tag="ip", tag_field="entity_type"):
    entity_id: UUID
    first_seen: int
    last_seen: int
    address: str
    version: int = 4               # 4 or 6
    is_private: bool = False
    is_tor_exit: bool = False
    asn: int | None = None
    asn_org: str | None = None
    geo_country: str | None = None
    geo_city: str | None = None

class HostEntity(msgspec.Struct, frozen=True, tag="host", tag_field="entity_type"):
    entity_id: UUID
    first_seen: int
    last_seen: int
    hostname: str
    fqdn: str | None = None
    os_family: str | None = None   # Windows | Linux | macOS
    ip_addresses: tuple[str, ...] = ()
    mac_addresses: tuple[str, ...] = ()

class ProcessEntity(msgspec.Struct, frozen=True, tag="process", tag_field="entity_type"):
    entity_id: UUID
    first_seen: int
    last_seen: int
    pid: int
    name: str
    command_line: str | None = None
    image_path: str | None = None
    hashes: dict[str, str] = {}    # md5, sha1, sha256
    parent_pid: int | None = None
    user: str | None = None
    host: str | None = None
    creation_time: int | None = None  # nanoseconds

class FileEntity(msgspec.Struct, frozen=True, tag="file", tag_field="entity_type"):
    entity_id: UUID
    first_seen: int
    last_seen: int
    path: str
    name: str = ""
    hashes: dict[str, str] = {}    # md5, sha1, sha256
    size: int | None = None
    owner: str | None = None

class DomainEntity(msgspec.Struct, frozen=True, tag="domain", tag_field="entity_type"):
    entity_id: UUID
    first_seen: int
    last_seen: int
    domain: str                     # eTLD+1 normalized
    registrar: str | None = None
    creation_date: int | None = None
    is_dga: bool = False            # Domain Generation Algorithm flag

# Discriminated union for any entity type
SecurityEntity = UserEntity | IPEntity | HostEntity | ProcessEntity | FileEntity | DomainEntity
```

### Entity Normalization Functions

```python
def normalize_username(raw: str, default_domain: str = "") -> tuple[str, str]:
    """Normalize username: strip domain prefix, lowercase."""
    raw = raw.strip()
    if "\\" in raw:  # DOMAIN\user
        domain, username = raw.split("\\", 1)
        return username.lower(), domain.lower()
    if "@" in raw:   # user@domain
        username, domain = raw.rsplit("@", 1)
        return username.lower(), domain.lower()
    return raw.lower(), default_domain.lower()

def generate_user_id(username: str, domain: str) -> UUID:
    canonical = f"{domain}:{username}" if domain else username
    return uuid.uuid5(NS_USER, canonical)

def generate_ip_id(raw: str) -> UUID:
    from ipaddress import ip_address, IPv6Address
    addr = ip_address(raw.strip())
    normalized = addr.exploded if isinstance(addr, IPv6Address) else str(addr)
    return uuid.uuid5(NS_IP, normalized)

def generate_host_id(hostname: str, domain: str = "") -> UUID:
    h = hostname.strip().lower().rstrip(".")
    canonical = f"{h}.{domain}" if domain and "." not in h else h
    return uuid.uuid5(NS_HOST, canonical)

def generate_process_id(hostname: str, pid: int, start_time: int) -> UUID:
    return uuid.uuid5(NS_PROCESS, f"{hostname}:{pid}:{start_time}")

def generate_file_id(path: str) -> UUID:
    return uuid.uuid5(NS_FILE, path.strip())

def generate_domain_id(domain: str) -> UUID:
    # Normalize to eTLD+1 (requires tldextract or manual logic)
    return uuid.uuid5(NS_DOMAIN, domain.strip().lower().rstrip("."))
```

### Entity Relationship Edge Model

Edges in the igraph entity graph track:

| Field | Type | Description |
|-------|------|-------------|
| `source_id` | str | Source entity UUID |
| `target_id` | str | Target entity UUID |
| `rel_type` | str | Relationship type (see below) |
| `first_seen` | int | Nanosecond timestamp of first observation |
| `last_seen` | int | Nanosecond timestamp of most recent observation |
| `event_count` | int | Number of events supporting this relationship |
| `event_ids` | list[str] | Sample of supporting event IDs (bounded, e.g., last 10) |

Core relationship types:

| Relationship | Source → Target | Example |
|-------------|----------------|---------|
| `logged_into` | User → Host | SSH/RDP login |
| `authenticated_from` | User → IP | Auth event source IP |
| `spawned_by` | Process → Process | Parent-child process |
| `resolved_to` | IP → Domain | DNS resolution |
| `accessed` | User → File | File read/write |
| `has_ip` | Host → IP | Network interface |
| `connected_to` | IP → IP | Network flow |

---

## Appendix D: Additional Storage Protocols

> Source: `docs/background/Designing Seerflow's event schema and storage backend.md`

### GraphStore Protocol

The architecture's igraph-based entity graph needs a Protocol interface for testability and potential backend swapping.

```python
@runtime_checkable
class GraphStore(Protocol):
    """Entity relationship graph operations."""
    async def add_edge(
        self, source_id: str, target_id: str, rel_type: str,
        timestamp_ns: int, properties: dict | None = None,
    ) -> None: ...
    async def get_neighbors(
        self, entity_id: str, rel_types: list[str] | None = None, depth: int = 1,
    ) -> list[dict]: ...
    async def shortest_path(self, source_id: str, target_id: str) -> list[str]: ...
    async def get_subgraph(
        self, entity_id: str, depth: int = 2
    ) -> tuple[list[dict], list[dict]]: ...
```

**Implementation note:** The primary implementation uses igraph in-memory. GraphStore Protocol enables future Redis Graph or PostgreSQL AGE backends.

### CheckpointStore Protocol

For ML model checkpoint persistence (alternative view of ModelStore):

```python
@runtime_checkable
class CheckpointStore(Protocol):
    """ML model checkpoint persistence."""
    async def save_checkpoint(
        self, model_name: str, version: str, data: bytes, metadata: dict,
    ) -> None: ...
    async def load_checkpoint(
        self, model_name: str, version: str | None = None,
    ) -> tuple[bytes, dict] | None: ...
    async def list_checkpoints(self, model_name: str) -> list[dict]: ...
```

**Design decision:** The architecture's `ModelStore` (key-value `save_state`/`load_state`) is simpler and sufficient for v1. `CheckpointStore` with versioning and metadata is a v1.1 upgrade path when model rollback becomes important.

### Query Types

```python
@dataclass(frozen=True, slots=True)
class TimeRange:
    start_ns: int
    end_ns: int

@dataclass(frozen=True, slots=True)
class EventFilter:
    """Composable filter for event queries. None fields are not applied."""
    time_range: TimeRange | None = None
    severity_min: int = 0
    source_types: list[str] | None = None
    template_ids: list[int] | None = None
    entity_ids: list[str] | None = None
    event_categories: list[str] | None = None
    text_query: str | None = None
    limit: int = 1000
    offset: int = 0
```

**Design decision:** The architecture uses `EventQuery` (with `page`/`limit` for REST API) while background uses `EventFilter` (with `offset`/`limit`). For S-003, use `EventQuery` with both `page` and `limit` since the REST API is the primary consumer. The background `EventFilter` fields inform which filters to support.

### WriteBuffer Pattern

```python
class WriteBuffer:
    """Batch events and flush periodically or when buffer is full."""
    def __init__(self, backend: LogStore, max_size: int = 10_000, flush_interval: float = 5.0):
        ...
    async def append(self, event: SeerflowEvent) -> None:
        """Add event; auto-flush if buffer full."""
        ...
    async def flush(self) -> None:
        """Write buffered events to backend."""
        ...
```

Used in S-006 (SQLite backend writes) — "Batch event writes (1000 events or 100ms, whichever first)".

---

## Appendix E: Detection Algorithm Specifications

> Source: `docs/background/Algorithms for online-learning log anomaly detection in Python.md`

### Feature Vectorization

**Decision: Message Count Vectors (MCV)** as the default feature extraction method.

Rationale (from Wu et al., 2023 benchmark): MCV ranked #1 overall across 6 representations and 7 ML models. Fast (microseconds), low-memory, and surprisingly effective (F1 ~0.95+ on HDFS with SVM).

Implementation: Count the frequency of each `template_id` in the current window. Each event's feature vector is a sparse count of template occurrences in its entity's recent history.

Alternatives available for future stories:
- **Online TF-IDF** via River — better for datasets with many rare templates
- **Feature hashing** (HashingVectorizer, n_features=128) — bounded memory, no vocabulary
- **Semantic embeddings** (all-MiniLM-L6-v2) — best with deep learning, highest cost

### DSPOT Configuration Parameters

```python
# Initial threshold: 98th percentile of calibration window
# Calibration window: 1000 events minimum (configurable)
# Risk level q: 1e-4 (0.01% false positive rate)
# GPD fitting: Maximum Likelihood Estimation
# DSPOT adds moving average detrend for non-stationary data
```

Configuration in `seerflow.yaml`:
```yaml
detection:
  dspot:
    calibration_window: 1000
    risk_level: 0.0001        # q = 1e-4
    initial_percentile: 98
```

### Holt-Winters Parameters

```python
class OnlineHoltWinters:
    def __init__(
        self,
        seasonal_period: int = 1440,   # daily seasonality on 1-min buckets
        alpha: float = 0.3,            # level smoothing
        beta: float = 0.1,             # trend smoothing
        gamma: float = 0.1,            # seasonal smoothing
        n_std: float = 3.0,            # anomaly threshold (std deviations)
    ): ...
```

### Ensemble Score Fusion

**Decision: Averaging** as the default fusion strategy.

Rationale: "Averaging is the most reliable default — it provably reduces variance under mild assumptions and outperforms all individual detectors in the TSB-UAD benchmark across 497 time series." (Algorithms doc)

Alternative: **MOA (Maximum of Average)** — split detectors into groups, average per group, take maximum — "most stable production strategy."

The blended scoring pipeline (architecture Section 3):
1. Each detector scores independently (0.0–1.0)
2. Z-normalize scores per detector (sliding window, per-source)
3. Weighted average: Content×0.30 + Volume×0.25 + Sequence×0.25 + Pattern×0.20
4. Signal amplification: 2 detectors converging = 1.5×, 3+ = 2.0×
5. DSPOT threshold comparison
6. Feedback loop adjustment (TP reinforces, FP adjusts threshold up)

### Watermark Pattern for Late Arrival

```python
class Watermark:
    """Track event-time progress with configurable late-arrival tolerance."""
    def __init__(self, max_delay_seconds: int = 30):
        self.max_delay = max_delay_seconds * 1_000_000_000  # nanoseconds
        self.watermark: int = 0

    def advance(self, event_time_ns: int) -> None:
        candidate = event_time_ns - self.max_delay
        if candidate > self.watermark:
            self.watermark = candidate

    def is_late(self, event_time_ns: int) -> bool:
        return event_time_ns < self.watermark
```

---

## Appendix F: Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-17 | Initial architecture |
| 1.1 | 2026-03-18 | Added Appendices C-E: entity type definitions, GraphStore/CheckpointStore Protocols, query types, detection algorithm specs. Sourced from background research docs. |
