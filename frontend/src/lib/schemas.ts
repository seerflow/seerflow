import * as v from "valibot";

const MAX_MESSAGE_BYTES = 16 * 1024;
const MAX_SOURCE_TYPE = 64;
const MITRE_RE = /^[A-Z][A-Z0-9.-]{0,31}$/;

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
  event_id: BoundedString(128),
  timestamp_ns: BigintNsSchema,
  observed_ns: BigintNsSchema,
  severity_id: v.pipe(v.number(), v.integer(), v.minValue(0), v.maxValue(6)),
  severity_text: BoundedString(16),
  source_type: BoundedString(MAX_SOURCE_TYPE),
  message: BoundedString(MAX_MESSAGE_BYTES),
  template_id: v.pipe(v.number(), v.integer(), v.minValue(0)),
  entity_refs: v.pipe(v.array(BoundedString(256)), v.maxLength(128)),
  entity_summary: EntitySummarySchema,
  score: v.optional(finite()),
  is_anomaly: v.optional(v.boolean()),
  upper_threshold: v.optional(finite()),
});

export const AlertTypeSchema = v.picklist(["ml", "sigma", "correlation", "ueba", "ioc"] as const);

export const AlertSchema = v.object({
  alert_id: BoundedString(128),
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
  feedback: v.optional(v.picklist(["", "tp", "fp"] as const)),
});

export const AlertDetailSchema = v.object({
  ...AlertSchema.entries,
  contributing_events: v.optional(v.pipe(
    v.array(v.object({
      event_id: BoundedString(128),
      timestamp_ns: BigintNsSchema,
      message: BoundedString(MAX_MESSAGE_BYTES),
    })),
    v.maxLength(50),
  )),
});

export type LiveEventInfer = v.InferOutput<typeof LiveEventSchema>;
export type AlertInfer = v.InferOutput<typeof AlertSchema>;
export type AlertDetailInfer = v.InferOutput<typeof AlertDetailSchema>;
