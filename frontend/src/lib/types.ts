export type AlertType = "ml" | "sigma" | "correlation" | "ueba" | "ioc";
export type SeverityBucket = "critical" | "high" | "medium" | "low";
export type WsStatus = "connecting" | "open" | "closed";
export type Feedback = "" | "tp" | "fp";

export interface Alert {
  alert_id: string;
  timestamp_ns: number;
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
};

export type WsMessage =
  | { type: "alert"; data: Alert }
  | { type: "status"; data: { events_per_sec: number; alerts_24h: number; connected_clients: number; dropped_messages: number } }
  | { type: "event"; data: unknown }
  | { type: "batch"; events: Alert[] };

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
