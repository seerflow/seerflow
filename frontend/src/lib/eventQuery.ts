/**
 * Client-side event query evaluator for the Events screen (S-329).
 *
 * Supports a minimal subset of the three query modes surfaced in the UI
 * (jq · sigma · sql) plus a free-text fallback. Evaluation runs over the
 * already-loaded / demo events — no server round-trip. An empty or invalid
 * query is non-blocking: it returns ALL events with a validity hint so the
 * stream never goes dark on a typo.
 */

import type { LiveEvent } from "@/lib/types";

export type QueryMode = "all" | "sigma" | "sql" | "jq" | "text";

export interface QueryResult {
  matched: LiveEvent[];
  valid: boolean;
  mode: QueryMode;
  hint?: string;
}

// Whitelisted event fields the query language can reference. Keeping this
// explicit lets unknown-field queries fail with a clear, non-blocking hint
// rather than silently matching nothing.
const QUERYABLE_FIELDS = new Set<string>([
  "event_id",
  "severity_id",
  "severity_text",
  "source_type",
  "message",
  "template_id",
]);

function fieldValue(e: LiveEvent, field: string): string | number | undefined {
  switch (field) {
    case "event_id":
      return e.event_id;
    case "severity_id":
      return e.severity_id;
    case "severity_text":
      return e.severity_text;
    case "source_type":
      return e.source_type;
    case "message":
      return e.message;
    case "template_id":
      return e.template_id;
    default:
      return undefined;
  }
}

function allResult(events: LiveEvent[], mode: QueryMode, hint?: string, valid = true): QueryResult {
  return { matched: events.slice(), valid, mode, hint };
}

// --- sigma: comma-separated `field: value` / `field=value` pairs (AND) ---

interface SigmaPair {
  field: string;
  value: string;
}

function parseSigma(query: string): SigmaPair[] | null {
  const parts = query.split(",").map((p) => p.trim()).filter(Boolean);
  if (parts.length === 0) return null;
  const pairs: SigmaPair[] = [];
  for (const part of parts) {
    const m = part.match(/^([a-z_][a-z0-9_]*)\s*[:=]\s*(.+)$/i);
    if (!m) return null;
    pairs.push({ field: m[1], value: m[2].trim().replace(/^["']|["']$/g, "") });
  }
  return pairs;
}

function evalSigma(events: LiveEvent[], query: string): QueryResult {
  const pairs = parseSigma(query);
  if (!pairs) return allResult(events, "sigma", "Unparseable sigma expression", false);
  const unknown = pairs.find((p) => !QUERYABLE_FIELDS.has(p.field));
  if (unknown) return allResult(events, "sigma", `Unknown field: ${unknown.field}`, false);
  const matched = events.filter((e) =>
    pairs.every((p) => {
      const v = fieldValue(e, p.field);
      return v != null && String(v).toLowerCase().includes(p.value.toLowerCase());
    }),
  );
  return { matched, valid: true, mode: "sigma" };
}

// --- sql: single `field op value` comparison ---

type SqlOp = "=" | "!=" | ">=" | "<=" | ">" | "<" | "contains";

const SQL_RE = /^([a-z_][a-z0-9_]*)\s*(>=|<=|!=|=|>|<|contains)\s*(.+)$/i;

function compare(actual: string | number | undefined, op: SqlOp, raw: string): boolean {
  if (actual == null) return false;
  const target = raw.trim().replace(/^["']|["']$/g, "");
  const numActual = typeof actual === "number" ? actual : Number(actual);
  const numTarget = Number(target);
  const numeric = !Number.isNaN(numActual) && !Number.isNaN(numTarget) && target !== "";
  switch (op) {
    case "contains":
      return String(actual).toLowerCase().includes(target.toLowerCase());
    case "=":
      return numeric ? numActual === numTarget : String(actual).toLowerCase() === target.toLowerCase();
    case "!=":
      return numeric ? numActual !== numTarget : String(actual).toLowerCase() !== target.toLowerCase();
    case ">=":
      return numeric && numActual >= numTarget;
    case "<=":
      return numeric && numActual <= numTarget;
    case ">":
      return numeric && numActual > numTarget;
    case "<":
      return numeric && numActual < numTarget;
    default:
      return false;
  }
}

function evalSql(events: LiveEvent[], query: string): QueryResult {
  const m = query.replace(/^where\s+/i, "").match(SQL_RE);
  if (!m) return allResult(events, "sql", "Unparseable sql expression", false);
  const [, field, op, raw] = m;
  if (!QUERYABLE_FIELDS.has(field)) return allResult(events, "sql", `Unknown field: ${field}`, false);
  const matched = events.filter((e) => compare(fieldValue(e, field), op.toLowerCase() as SqlOp, raw));
  return { matched, valid: true, mode: "sql" };
}

// --- jq: `.field == value` or `select(.field op value)` ---

const JQ_RE = /\.([a-z_][a-z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*\)?$/i;

function evalJq(events: LiveEvent[], query: string): QueryResult {
  const inner = query.replace(/^select\s*\(/i, "").trim();
  const m = inner.match(JQ_RE);
  if (!m) return allResult(events, "jq", "Unparseable jq expression", false);
  const [, field, op, raw] = m;
  if (!QUERYABLE_FIELDS.has(field)) return allResult(events, "jq", `Unknown field: ${field}`, false);
  const sqlOp = (op === "==" ? "=" : op) as SqlOp;
  const matched = events.filter((e) => compare(fieldValue(e, field), sqlOp, raw));
  return { matched, valid: true, mode: "jq" };
}

// --- free text fallback: substring over message ---

function evalText(events: LiveEvent[], query: string): QueryResult {
  const needle = query.toLowerCase();
  const matched = events.filter((e) => e.message.toLowerCase().includes(needle));
  return { matched, valid: true, mode: "text" };
}

/**
 * Evaluate a query string against a set of events. Mode is auto-detected from
 * the query syntax. Empty / invalid queries return all events (non-blocking).
 */
export function applyEventQuery(events: LiveEvent[], query: string): QueryResult {
  const q = query.trim();
  if (q === "") return allResult(events, "all");

  // jq — leading dot accessor or a select(...) wrapper.
  if (q.startsWith(".") || /^select\s*\(/i.test(q)) return evalJq(events, q);

  // sql — explicit WHERE, a relational operator (>=, <=, !=, >, <), the
  // `contains` keyword, or a spaced `=` equality. Sigma uses `:` or a bare
  // (unspaced) `=`, so the spacing/operator distinguishes the two.
  if (/^where\s+/i.test(q) || /(>=|<=|!=|>|<)/.test(q) || /\bcontains\b/i.test(q) || /\s=\s/.test(q)) {
    return evalSql(events, q);
  }

  // sigma — one or more `field: value` / `field=value` pairs.
  if (/[:=]/.test(q)) return evalSigma(events, q);

  // free-text fallback over message.
  return evalText(events, q);
}

/**
 * Count crit / warn events using the EventStream-local convention
 * (crit = severity_id >= 6, warn = severity_id >= 4 and < 6) so the summary
 * stays consistent with the row coloring users already see.
 */
export function countSeverities(events: LiveEvent[]): { crit: number; warn: number } {
  let crit = 0;
  let warn = 0;
  for (const e of events) {
    if (e.severity_id >= 6) crit++;
    else if (e.severity_id >= 4) warn++;
  }
  return { crit, warn };
}
