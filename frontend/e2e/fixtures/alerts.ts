// S-195 fixtures.
//
// `timestamp_ns` MUST be emitted as a JSON string (S-194 wire format). The
// frontend `api.ts::reviveAlertTimestamps` parses the string back to a
// `bigint` on the REST boundary. Writing a numeric literal here would round
// the nanosecond precision silently — do not "normalise" these strings.
//
// Alert IDs use disjoint ranges to avoid the alert-store dedup merge
// (keeps higher `timestamp_ns` on collision) silently failing the
// live-stream assertion:
//   * wu-*   -- warm-up REST payload
//   * lp-*   -- live WS push

export type FixtureAlert = {
  alert_id: string;
  timestamp_ns: string;
  alert_type: "ml" | "sigma" | "correlation" | "ueba" | "ioc";
  rule_name: string;
  severity: number;
  risk_score: number;
  entity_uuid: string | null;
  entity_type: string | null;
  entity_value: string | null;
  message: string;
  mitre_tactics: string[];
  mitre_techniques: string[];
  dedup_count: number;
  source_type?: string;
  feedback?: "" | "tp" | "fp";
};

export type FixtureAlertDetail = FixtureAlert & {
  contributing_events?: Array<{ event_id: string; timestamp_ns: bigint; message: string }>;
};

// Five warm-up alerts. Severity buckets (per SEE-58 mapping, 17-24=critical,
// 13-16=high, 9-12=medium, 1-8=low): two critical (20, 18), one high (14),
// one medium (10), one low (5).
export const warmUpAlerts: FixtureAlert[] = [
  {
    alert_id: "wu-001",
    timestamp_ns: "1700000000000000001",
    alert_type: "sigma",
    rule_name: "Suspicious PowerShell",
    severity: 20,
    risk_score: 85,
    entity_uuid: "uuid-host-1",
    entity_type: "host",
    entity_value: "host-1",
    message: "Encoded PS command",
    mitre_tactics: ["execution"],
    mitre_techniques: ["T1059.001"],
    dedup_count: 1,
    source_type: "windows",
  },
  {
    alert_id: "wu-002",
    timestamp_ns: "1700000000000000002",
    alert_type: "ml",
    rule_name: "Volume spike",
    severity: 14,
    risk_score: 60,
    entity_uuid: "uuid-host-2",
    entity_type: "host",
    entity_value: "host-2",
    message: "3x baseline",
    mitre_tactics: ["impact"],
    mitre_techniques: ["T1499"],
    dedup_count: 1,
    source_type: "linux",
  },
  {
    alert_id: "wu-003",
    timestamp_ns: "1700000000000000003",
    alert_type: "correlation",
    rule_name: "Brute force",
    severity: 10,
    risk_score: 45,
    entity_uuid: "uuid-user-alice",
    entity_type: "user",
    entity_value: "alice",
    message: "12 failed logins",
    mitre_tactics: ["credential-access"],
    mitre_techniques: ["T1110"],
    dedup_count: 1,
    source_type: "auth",
  },
  {
    alert_id: "wu-004",
    timestamp_ns: "1700000000000000004",
    alert_type: "ioc",
    rule_name: "Known-bad IP",
    severity: 5,
    risk_score: 25,
    entity_uuid: "uuid-ip-1234",
    entity_type: "ip",
    entity_value: "1.2.3.4",
    message: "Outbound to flagged host",
    mitre_tactics: ["command-and-control"],
    mitre_techniques: ["T1071"],
    dedup_count: 1,
    source_type: "network",
  },
  {
    alert_id: "wu-005",
    timestamp_ns: "1700000000000000005",
    alert_type: "sigma",
    rule_name: "Registry autorun",
    severity: 18,
    risk_score: 78,
    entity_uuid: "uuid-host-3",
    entity_type: "host",
    entity_value: "host-3",
    message: "HKCU\\Run modified",
    mitre_tactics: ["persistence"],
    mitre_techniques: ["T1547"],
    dedup_count: 1,
    source_type: "windows",
  },
];

// Live-pushed alert (severity 22 -> critical bucket).
export const livePushAlert: FixtureAlert = {
  alert_id: "lp-100",
  timestamp_ns: "1700000000000000999",
  alert_type: "sigma",
  rule_name: "Mimikatz detected",
  severity: 22,
  risk_score: 95,
  entity_uuid: "uuid-host-9",
  entity_type: "host",
  entity_value: "host-9",
  message: "Credential dumping tool",
  mitre_tactics: ["credential-access"],
  mitre_techniques: ["T1003"],
  dedup_count: 1,
  source_type: "windows",
};

// Paginated list envelope the frontend expects at GET /api/v1/alerts.
export function listEnvelope(alerts: FixtureAlert[]): {
  items: FixtureAlert[];
  total: number;
  page: number;
  limit: number;
  has_next: boolean;
} {
  return {
    items: alerts,
    total: alerts.length,
    page: 1,
    limit: 50,
    has_next: false,
  };
}

// Detail fixture for an alert id in `warmUpAlerts`. Shape = `AlertDetail`
// (extends Alert) with two contributing events and three MITRE techniques.
export function detailFor(id: string): FixtureAlertDetail {
  const base =
    warmUpAlerts.find((a) => a.alert_id === id) ?? warmUpAlerts[0];
  return {
    ...base,
    mitre_techniques: ["T1059.001", "T1547", "T1055"],
    mitre_tactics: ["execution", "persistence"],
    contributing_events: [
      {
        event_id: "evt-1",
        timestamp_ns: 1_700_000_000_000_000n,
        message: "Process launched",
      },
      {
        event_id: "evt-2",
        timestamp_ns: 1_700_000_000_000_001n,
        message: "Network connection",
      },
    ],
  };
}
