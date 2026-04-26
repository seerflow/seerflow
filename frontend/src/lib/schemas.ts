import * as v from "valibot";
import { incrementDropped, warnThrottled } from "./validationMetrics";

const MAX_MESSAGE_BYTES = 16 * 1024;
const MAX_SOURCE_TYPE = 64;
// Accepts both uppercase technique IDs (e.g., "T1059.001") and lowercase
// kebab-case tactic names (e.g., "execution", "credential-access"). Backend
// emits tactic names in canonical lowercase form (see
// `src/seerflow/sigma/attack.py::TACTICS`) while techniques are uppercase.
// 32-char cap is preserved as a DoS guard for the regex engine.
const MITRE_RE = /^[A-Za-z][A-Za-z0-9.-]{0,31}$/;
// alert_id / event_id flow into URL paths (e.g. /api/v1/alerts/${id}/feedback)
// so must not contain path separators, slashes, dots, or whitespace. Length-only
// bounds would let a crafted "../foo" pivot requests to arbitrary same-origin
// paths on a compromised backend. 128 chars is large enough for UUIDs and
// prefixed keys ("alert_<ulid>") while rejecting traversal vectors.
const SAFE_ID_RE = /^[A-Za-z0-9_-]{1,128}$/;
const SafeId = v.pipe(v.string(), v.regex(SAFE_ID_RE));

const finite = () =>
  v.pipe(v.number(), v.check((n: number) => Number.isFinite(n), "must be finite"));

const BigintNsSchema = v.pipe(v.bigint(), v.check((n) => n >= 0n, "ns timestamp must be >= 0"));

const BoundedString = (max: number) =>
  v.pipe(v.string(), v.maxLength(max));

const EntitySummarySchema = v.strictObject({
  ips: v.optional(v.pipe(v.array(BoundedString(256)), v.maxLength(64))),
  users: v.optional(v.pipe(v.array(BoundedString(256)), v.maxLength(64))),
  hosts: v.optional(v.pipe(v.array(BoundedString(256)), v.maxLength(64))),
  domains: v.optional(v.pipe(v.array(BoundedString(256)), v.maxLength(64))),
  files: v.optional(v.pipe(v.array(BoundedString(256)), v.maxLength(64))),
  processes: v.optional(v.pipe(v.array(BoundedString(256)), v.maxLength(64))),
});

export const LiveEventSchema = v.object({
  event_id: SafeId,
  timestamp_ns: BigintNsSchema,
  observed_ns: BigintNsSchema,
  severity_id: v.pipe(v.number(), v.integer(), v.minValue(0), v.maxValue(6)),
  severity_text: BoundedString(16),
  source_type: BoundedString(MAX_SOURCE_TYPE),
  message: BoundedString(MAX_MESSAGE_BYTES),
  template_id: v.pipe(v.number(), v.integer(), v.minValue(0)),
  entity_refs: v.pipe(v.array(BoundedString(256)), v.maxLength(128)),
  entity_summary: v.optional(EntitySummarySchema),
  score: v.optional(finite()),
  is_anomaly: v.optional(v.boolean()),
  upper_threshold: v.optional(finite()),
});

export const AlertTypeSchema = v.picklist(["ml", "sigma", "correlation", "ueba", "ioc"] as const);

export const AlertSchema = v.object({
  alert_id: SafeId,
  timestamp_ns: BigintNsSchema,
  alert_type: AlertTypeSchema,
  rule_name: BoundedString(256),
  severity: v.pipe(v.number(), v.integer(), v.minValue(0), v.maxValue(6)),
  risk_score: v.pipe(finite(), v.minValue(0), v.maxValue(1)),
  entity_uuid: v.union([BoundedString(64), v.null_()]),
  entity_type: v.union([BoundedString(64), v.null_()]),
  entity_value: v.union([BoundedString(256), v.null_()]),
  message: BoundedString(MAX_MESSAGE_BYTES),
  mitre_tactics: v.pipe(v.array(v.pipe(v.string(), v.regex(MITRE_RE))), v.maxLength(32)),
  mitre_techniques: v.pipe(v.array(v.pipe(v.string(), v.regex(MITRE_RE))), v.maxLength(32)),
  dedup_count: v.pipe(v.number(), v.integer(), v.minValue(0)),
  source_type: v.optional(BoundedString(MAX_SOURCE_TYPE)),
  feedback: v.nullish(v.picklist(["", "tp", "fp"] as const)),
});

export const AlertDetailSchema = v.object({
  ...AlertSchema.entries,
  contributing_events: v.optional(v.pipe(
    v.array(v.object({
      event_id: SafeId,
      timestamp_ns: BigintNsSchema,
      message: BoundedString(MAX_MESSAGE_BYTES),
    })),
    v.maxLength(50),
  )),
});

export type LiveEventInfer = v.InferOutput<typeof LiveEventSchema>;
export type AlertInfer = v.InferOutput<typeof AlertSchema>;
export type AlertDetailInfer = v.InferOutput<typeof AlertDetailSchema>;

const NS_WIRE_RE = /^\d{1,25}$/;
const NsWireStringSchema = v.pipe(v.string(), v.regex(NS_WIRE_RE));

const AlertWireSchema = v.object({
  ...AlertSchema.entries,
  timestamp_ns: NsWireStringSchema,
});

const LiveEventWireSchema = v.object({
  ...LiveEventSchema.entries,
  timestamp_ns: NsWireStringSchema,
  observed_ns: NsWireStringSchema,
});

const StatusDataSchema = v.object({
  events_ingested_per_sec: finite(),
  alerts_24h: finite(),
  connected_clients: finite(),
  dropped_events: finite(),
  dropped_alerts: finite(),
  dropped_total: finite(),
});

export const WsMessageWireSchema = v.variant("type", [
  v.object({ type: v.literal("alert"),       data: AlertWireSchema }),
  v.object({ type: v.literal("alert_batch"), alerts: v.pipe(v.array(AlertWireSchema), v.maxLength(100)) }),
  v.object({ type: v.literal("status"),      data: StatusDataSchema }),
  v.object({ type: v.literal("event"),       data: LiveEventWireSchema }),
  v.object({
    type: v.literal("batch"),
    // Backend only puts LiveEvents in `batch`; alerts ship through `alert_batch`.
    events: v.pipe(v.array(LiveEventWireSchema), v.maxLength(500)),
  }),
]);

export const WsMessageSchema = v.variant("type", [
  v.object({ type: v.literal("alert"),       data: AlertSchema }),
  v.object({ type: v.literal("alert_batch"), alerts: v.pipe(v.array(AlertSchema), v.maxLength(100)) }),
  v.object({ type: v.literal("status"),      data: StatusDataSchema }),
  v.object({ type: v.literal("event"),       data: LiveEventSchema }),
  v.object({
    type: v.literal("batch"),
    events: v.pipe(v.array(LiveEventSchema), v.maxLength(500)),
  }),
]);

export type WsMessageInfer = v.InferOutput<typeof WsMessageSchema>;

function reviveAlert(a: v.InferOutput<typeof AlertWireSchema>): v.InferOutput<typeof AlertSchema> {
  return { ...a, timestamp_ns: BigInt(a.timestamp_ns) };
}

function reviveEvent(e: v.InferOutput<typeof LiveEventWireSchema>): v.InferOutput<typeof LiveEventSchema> {
  return { ...e, timestamp_ns: BigInt(e.timestamp_ns), observed_ns: BigInt(e.observed_ns) };
}

function inferKind(raw: unknown): string {
  if (raw && typeof raw === "object" && "type" in raw) {
    const t = (raw as { type: unknown }).type;
    if (typeof t === "string" &&
        ["alert", "alert_batch", "status", "event", "batch"].includes(t)) {
      return `ws:${t}`;
    }
  }
  return "ws:unknown";
}

export function parseWsFrame(raw: unknown): WsMessageInfer | null {
  const kind = inferKind(raw);
  const wire = v.safeParse(WsMessageWireSchema, raw);
  if (!wire.success) {
    incrementDropped(kind);
    warnThrottled(kind, wire.issues.map(i => ({ kind: i.kind, type: i.type, path: i.path?.map(p => p.key) })));
    return null;
  }
  const w = wire.output;
  let revived: WsMessageInfer;
  switch (w.type) {
    case "alert":
      revived = { type: "alert", data: reviveAlert(w.data) };
      break;
    case "alert_batch":
      revived = { type: "alert_batch", alerts: w.alerts.map(reviveAlert) };
      break;
    case "status":
      revived = { type: "status", data: w.data };
      break;
    case "event":
      revived = { type: "event", data: reviveEvent(w.data) };
      break;
    case "batch":
      revived = { type: "batch", events: w.events.map(reviveEvent) };
      break;
  }
  const deep = v.safeParse(WsMessageSchema, revived);
  /* v8 ignore start */
  // Defensive: unreachable when reviveAlert/reviveEvent are correct, since the
  // revived shape is a strict superset of what WsMessageWireSchema already
  // accepted (bigint replaces string). Kept so a future regression in a revive
  // helper is caught at the boundary instead of reaching the store.
  if (!deep.success) {
    incrementDropped(kind);
    warnThrottled(kind, deep.issues.map(i => ({ kind: i.kind, type: i.type, path: i.path?.map(p => p.key) })));
    return null;
  }
  /* v8 ignore stop */
  return deep.output;
}

export function PaginatedResponseSchema<T extends v.BaseSchema<unknown, unknown, v.BaseIssue<unknown>>>(item: T) {
  return v.object({
    items: v.pipe(v.array(item), v.maxLength(1000)),
    total: v.pipe(v.number(), v.integer(), v.minValue(0), v.maxValue(10_000_000)),
    page: v.pipe(v.number(), v.integer(), v.minValue(0)),
    limit: v.pipe(v.number(), v.integer(), v.minValue(0), v.maxValue(1000)),
    has_next: v.boolean(),
  });
}

export function validateOrDropItem<T extends v.BaseSchema<unknown, unknown, v.BaseIssue<unknown>>>(
  schema: T,
  raw: unknown,
  kind: string,
): v.InferOutput<T> | null {
  const r = v.safeParse(schema, raw);
  if (r.success) return r.output as v.InferOutput<T>;
  incrementDropped(kind);
  warnThrottled(kind, r.issues.map(i => ({ kind: i.kind, type: i.type, path: i.path?.map(p => p.key) })));
  return null;
}

// ---------------------------------------------------------------------------
// Sigma rules management (S-151)
// ---------------------------------------------------------------------------

export const SigmaRuleSourceSchema = v.picklist([
  "bundled",
  "custom",
  "custom_uploaded",
] as const);

const SigmaLogsourceTuple = v.pipe(
  v.array(v.pipe(v.string(), v.maxLength(64))),
  v.length(3),
);

export const SigmaRuleSummarySchema = v.object({
  rule_id: v.pipe(v.string(), v.maxLength(64)),
  title: v.pipe(v.string(), v.maxLength(512)),
  description: v.pipe(v.string(), v.maxLength(8192)),
  severity: v.pipe(v.number(), v.integer(), v.minValue(0), v.maxValue(24)),
  logsource_key: SigmaLogsourceTuple,
  attack_tactics: v.pipe(v.array(v.pipe(v.string(), v.maxLength(64))), v.maxLength(32)),
  attack_techniques: v.pipe(v.array(v.pipe(v.string(), v.maxLength(64))), v.maxLength(32)),
  enabled: v.boolean(),
  source: SigmaRuleSourceSchema,
  match_count_lifetime: v.pipe(v.number(), v.integer(), v.minValue(0)),
  last_fired_ns: v.nullable(v.pipe(v.number(), v.integer(), v.minValue(0))),
  alert_count_24h: v.pipe(v.number(), v.integer(), v.minValue(0)),
});

export const SigmaRuleDetailSchema = v.object({
  ...SigmaRuleSummarySchema.entries,
  yaml_source: v.pipe(v.string(), v.maxLength(65_536)),
});

export const SigmaRuleListResponseSchema = v.object({
  items: v.pipe(v.array(SigmaRuleSummarySchema), v.maxLength(500)),
  total: v.pipe(v.number(), v.integer(), v.minValue(0)),
  page: v.pipe(v.number(), v.integer(), v.minValue(1)),
  limit: v.pipe(v.number(), v.integer(), v.minValue(1)),
});

export const SigmaRuleValidationStageSchema = v.picklist([
  "yaml",
  "schema",
  "compile",
] as const);

export const SigmaRuleValidationResultSchema = v.object({
  valid: v.boolean(),
  rule_id: v.optional(v.pipe(v.string(), v.maxLength(64))),
  title: v.optional(v.pipe(v.string(), v.maxLength(512))),
  logsource_key: v.optional(SigmaLogsourceTuple),
  stage: v.optional(SigmaRuleValidationStageSchema),
  message: v.optional(v.pipe(v.string(), v.maxLength(4096))),
  line: v.optional(v.pipe(v.number(), v.integer(), v.minValue(0))),
  column: v.optional(v.pipe(v.number(), v.integer(), v.minValue(0))),
  field: v.optional(v.pipe(v.string(), v.maxLength(128))),
});

export type SigmaRuleSummaryInfer = v.InferOutput<typeof SigmaRuleSummarySchema>;
export type SigmaRuleDetailInfer = v.InferOutput<typeof SigmaRuleDetailSchema>;
export type SigmaRuleListResponseInfer = v.InferOutput<
  typeof SigmaRuleListResponseSchema
>;
export type SigmaRuleValidationResultInfer = v.InferOutput<
  typeof SigmaRuleValidationResultSchema
>;

// ---------------------------------------------------------------------------
// Feedback audit log (S-210 — defence-in-depth on top of the walker-level
// prototype-pollution guard from S-191). NOTE_MAX_LENGTH_FE must stay aligned
// with src/seerflow/utils/text.py::NOTE_MAX_LENGTH (single-source-of-truth on
// the backend; FE side is a manual mirror — see S-210 brainstorm rationale).
// ---------------------------------------------------------------------------

export const NOTE_MAX_LENGTH_FE = 512;

export const FeedbackOriginSchema = v.picklist([
  "dashboard",
  "cli",
  "api",
] as const);

export const FeedbackVerdictSchema = v.picklist(["tp", "fp"] as const);

export const FeedbackEventSchema = v.object({
  id: v.pipe(v.number(), v.integer(), v.minValue(0)),
  feedback: FeedbackVerdictSchema,
  note: v.pipe(v.string(), v.maxLength(NOTE_MAX_LENGTH_FE)),
  origin: FeedbackOriginSchema,
  submitted_at_ns: BigintNsSchema,
});

export const FeedbackHistoryResponseSchema = v.object({
  items: v.pipe(v.array(FeedbackEventSchema), v.maxLength(1000)),
  total: v.pipe(v.number(), v.integer(), v.minValue(0)),
  page: v.pipe(v.number(), v.integer(), v.minValue(1)),
  limit: v.pipe(v.number(), v.integer(), v.minValue(0), v.maxValue(1000)),
  has_next: v.boolean(),
});

export type FeedbackEventInfer = v.InferOutput<typeof FeedbackEventSchema>;
export type FeedbackHistoryResponseInfer = v.InferOutput<
  typeof FeedbackHistoryResponseSchema
>;
