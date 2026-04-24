export type AlertType = "ml" | "sigma" | "correlation" | "ueba" | "ioc";
export type SeverityBucket = "critical" | "high" | "medium" | "low";
export type WsStatus = "connecting" | "open" | "closed";
export type Feedback = "" | "tp" | "fp";

export interface Alert {
  alert_id: string;
  timestamp_ns: bigint;        // S-194: serialised as JSON string by backend, parsed at REST/WS boundary
  alert_type: AlertType;
  rule_name: string;
  severity: number;                   // wire field = severity_id
  risk_score: number;
  entity_uuid: string | null;
  entity_type: string | null;
  entity_value: string | null;
  message: string;
  mitre_tactics: string[];
  mitre_techniques: string[];
  dedup_count: number;
  source_type?: string;
  feedback?: Feedback | null;
}

export interface AlertDetail extends Alert {
  contributing_events?: Array<{ event_id: string; timestamp_ns: bigint; message: string }>;
}

export interface AlertFilter {
  severities: Set<SeverityBucket>;   // empty = all
  types: Set<AlertType>;             // empty = all
  sources: Set<string>;              // empty = all
  tactics: Set<string>;              // empty = all
}

export type WsFilter = {
  type: "filter";
  sources?: string[];
  min_severity?: number;
  alert_types?: AlertType[];
  template_ids?: number[];
};

export type WsMessage =
  | { type: "alert"; data: Alert }
  | { type: "alert_batch"; alerts: Alert[] }
  | { type: "status"; data: { events_ingested_per_sec: number; alerts_24h: number; connected_clients: number; dropped_events: number; dropped_alerts: number; dropped_total: number } }
  | { type: "event"; data: LiveEvent }
  | { type: "batch"; events: LiveEvent[] | Alert[] }
  // S-062 internal: synthetic bus-only status frame emitted by WsProvider so
  // the global DisconnectedBanner and per-widget pips can subscribe uniformly
  // to connection-lifecycle changes. Never arrives from the network.
  // Any exhaustive `switch (msg.type)` over this union must handle or narrow
  // `"__status"` away (e.g., `case "__status": return;`).
  | { type: "__status"; status: WsStatus };

export type TimelineRange = "1h" | "6h" | "24h" | "7d";
export type TimelineResolution = "1m" | "5m" | "15m" | "1h";

export interface TimelineBucket {
  /** Bucket start as nanoseconds since epoch (bigint, wire JSON string — S-199). */
  bucket_start_ns: bigint;
  max_score: number | null;
  avg_score: number | null;
  event_count: number;
  upper_threshold: number | null;
  alert_count: number;
}

export interface TimelineMeta {
  range: TimelineRange;
  resolution: TimelineResolution;
  source: string | null;
  alert_count_truncated?: boolean;
}

export interface TimelineResponse {
  meta: TimelineMeta;
  items: TimelineBucket[];
}

export interface AnomalyEvent {
  timestamp_ns: bigint;
  score: number;
  upper_threshold: number | null;
  source_type: string;
}

// --- Entity explorer (S-060) ---

export type EntityType = "ip" | "user" | "host" | "domain";
export type RelationType =
  | "authenticated_from"
  | "logged_into"
  | "has_ip"
  | "accessed"
  | "resolved_to"
  | "spawned_by";

export interface EntitySearchResult {
  entity_type: EntityType | string; // server returns string; narrow on display
  entity_value: string;
  entity_uuid: string;
}

export interface EntityRelation {
  entity_uuid: string;
  entity_type: string;
  entity_value: string;
  relation_type: RelationType | string;
}

export interface EntityEvent {
  event_id: string;
  timestamp_ns: bigint;
  source_type: string;
  severity_id: number;
  message: string;
  related_ips: string[];
  related_users: string[];
  related_hosts: string[];
  related_domains: string[];
}

export interface EntityTimelineResponse {
  entity_uuid: string;
  events: EntityEvent[];
  related: EntityRelation[];
  total: number;
}

export interface EntityViewState {
  entity_uuid: string;
  range: TimelineRange;
  source?: string;
  severity_min?: number;
}

// --- Live event stream (S-061) ---

export interface LiveEvent {
  event_id: string;
  timestamp_ns: bigint;
  observed_ns: bigint;
  severity_id: number;       // 0..6
  severity_text: string;
  source_type: string;
  message: string;
  template_id: number;
  entity_refs: string[];
  entity_summary?: Partial<Record<"ips" | "users" | "hosts" | "domains" | "files" | "processes", string[]>>;
  score?: number;
  is_anomaly?: boolean;
  upper_threshold?: number;
}

export interface EventFilter {
  sources: Set<string>;       // empty = all
  minSeverity: number;        // 0..6, default 0
  templateIds: Set<number>;   // empty = all
}

// --- ATT&CK coverage heatmap (S-174) ---

export interface AttackCoverageCell {
  tactic: string;
  technique: string;
  rule_count: number;
  alert_count: number;
  covered: boolean;
  detected: boolean;
  rule_names: string[];
}

export interface AttackCoverageTactic {
  tactic: string;
  tactic_display_name: string;
  techniques: AttackCoverageCell[];
}

export interface AttackCoverageSummary {
  total_techniques_covered: number;
  total_techniques_detected: number;
  total_rules_with_attack_tags: number;
  total_alerts_matched: number;
}

export interface AttackCoverageResponse {
  window_since: string;
  window_until: string;
  tactics: AttackCoverageTactic[];
  summary: AttackCoverageSummary;
}

// --- Feedback audit log (S-066) ---

export type FeedbackOrigin = "dashboard" | "cli" | "api";

export interface FeedbackEvent {
  id: number;                // server-assigned autoincrement; stable React key
  feedback: "tp" | "fp";
  note: string;
  origin: FeedbackOrigin;
  submitted_at_ns: bigint;   // JSON string on wire (JS bigint safety)
}

export interface FeedbackHistoryResponse {
  items: FeedbackEvent[];
  total: number;
  page: number;
  limit: number;
  has_next: boolean;
}

// --- S-208: bus-facing vs wire-arrival union split ---
// `WireWsMessage` is the subset of `WsMessage` that can actually arrive on
// the network. `WsProvider` synthesises the `__status` variant internally;
// wire frames never carry it. Derived via `Exclude` so new wire variants
// propagate automatically when added to `WsMessage`.
export type WireWsMessage = Exclude<WsMessage, { type: "__status" }>;

// --- S-208: structural type guards for heterogeneous batch envelopes ---
// Used by AlertFeed / EventStream to discriminate `batch` payloads where the
// wire envelope carries `events: LiveEvent[] | Alert[]`. Checks are
// structural on the discriminator id field the widgets already rely on.
export function isAlert(x: unknown): x is Alert {
  return (
    typeof x === "object" &&
    x !== null &&
    Object.hasOwn(x, "alert_id") &&
    typeof (x as { alert_id: unknown }).alert_id === "string" &&
    !Object.hasOwn(x, "event_id")
  );
}

export function isLiveEvent(x: unknown): x is LiveEvent {
  return (
    typeof x === "object" &&
    x !== null &&
    Object.hasOwn(x, "event_id") &&
    typeof (x as { event_id: unknown }).event_id === "string" &&
    !Object.hasOwn(x, "alert_id")
  );
}

// ---------------------------------------------------------------------------
// Sigma rules management (S-151)
// ---------------------------------------------------------------------------

export type SigmaRuleSource = "bundled" | "custom" | "custom_uploaded";
export type SigmaValidationStage = "yaml" | "schema" | "compile";

export interface SigmaRuleSummary {
  rule_id: string;
  title: string;
  description: string;
  severity: number;
  logsource_key: [string, string, string];
  attack_tactics: string[];
  attack_techniques: string[];
  enabled: boolean;
  source: SigmaRuleSource;
  match_count_lifetime: number;
  last_fired_ns: number | null;
  alert_count_24h: number;
}

export interface SigmaRuleDetail extends SigmaRuleSummary {
  yaml_source: string;
}

export interface SigmaRuleListResponse {
  items: SigmaRuleSummary[];
  total: number;
  page: number;
  limit: number;
}

export interface SigmaRuleValidationResult {
  valid: boolean;
  rule_id?: string;
  title?: string;
  logsource_key?: [string, string, string];
  stage?: SigmaValidationStage;
  message?: string;
  line?: number;
  column?: number;
  field?: string;
}

export interface SigmaRuleFilter {
  search: string;
  category: string | null;
  logsource_product: string | null;
  severity: number | null;
  enabledOnly: boolean;
  source: SigmaRuleSource | null;
}

// S-060.F1: risk-history types.
export type RiskBucket = {
  // Serialized as a string on the wire for JS bigint safety (S-199 pattern).
  bucket_start_ns: string;
  points: number;
  alert_count: number;
  top_rule_name: string;
};

export type RiskHistoryMeta = {
  range: TimelineRange;
  resolution: "1m" | "5m" | "15m" | "1h";
  alert_count_truncated: boolean;
};

export type RiskHistoryResponse = {
  meta: RiskHistoryMeta;
  items: RiskBucket[];
};
