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
  feedback?: Feedback;
}

export interface AlertDetail extends Alert {
  contributing_events?: Array<{ event_id: string; timestamp_ns: number; message: string }>;
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
  | { type: "batch"; events: LiveEvent[] | Alert[] };

export type TimelineRange = "1h" | "6h" | "24h" | "7d";
export type TimelineResolution = "1m" | "5m" | "15m" | "1h";

export interface TimelineBucket {
  bucket_start_ns: number;
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
}

export interface TimelineResponse {
  meta: TimelineMeta;
  items: TimelineBucket[];
}

export interface AnomalyEvent {
  timestamp_ns: number;
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
  timestamp_ns: number;
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
  timestamp_ns: number;
  observed_ns: number;
  severity_id: number;       // 0..6
  severity_text: string;
  source_type: string;
  message: string;
  template_id: number;
  entity_refs: string[];
  entity_summary: Partial<Record<"ips" | "users" | "hosts" | "domains" | "files" | "processes", string[]>>;
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
