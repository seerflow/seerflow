import { memo, useMemo } from "react";
import type { LiveEvent } from "@/lib/types";
import { SFBadge } from "@/components/ui/primitives/Badge";

interface Props {
  event: LiveEvent;
  expanded: boolean;
  onToggle: (eventId: string) => void;
}

const MAX_MSG = 240;

// ---------------------------------------------------------------------------
// Timestamp formatting
// ---------------------------------------------------------------------------

function fmtTs(ns: bigint): string {
  const d = new Date(Number(ns / 1_000_000n));
  const pad = (n: number, w = 2): string => n.toString().padStart(w, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
}

// ---------------------------------------------------------------------------
// Severity helpers
// ---------------------------------------------------------------------------

type SevLevel = "info" | "warn" | "crit" | "mute";

function sevLevel(id: number): SevLevel {
  if (id >= 6) return "crit";
  if (id >= 4) return "warn";
  if (id >= 2) return "info";
  return "mute";
}

function sevColor(level: SevLevel): string {
  if (level === "crit") return "var(--crit)";
  if (level === "warn") return "var(--warn)";
  if (level === "info") return "var(--text-2)";
  return "var(--text-3)";
}

function rowBackground(level: SevLevel): string {
  if (level === "crit") return "color-mix(in oklch, var(--crit) 8%, transparent)";
  if (level === "warn") return "color-mix(in oklch, var(--warn) 4%, transparent)";
  return "transparent";
}

// ---------------------------------------------------------------------------
// Tag detection
// ---------------------------------------------------------------------------

interface EventTags {
  sigma: string | null;
  killChain: boolean;
  anomaly: boolean;
}

function detectTags(event: LiveEvent): EventTags {
  const msg = event.message ?? "";
  const sigma = msg.includes("[T") ? extractSigmaTag(msg) : null;
  const killChain = msg.startsWith("kill_chain") || (typeof event.score === "number" && msg.includes("kill_chain"));
  const anomaly = event.is_anomaly === true;
  return { sigma, killChain, anomaly };
}

function extractSigmaTag(msg: string): string | null {
  // Look for "sigma: rule_name" or "[TXXXX.YYY]" patterns
  const sigmaMatch = msg.match(/sigma:\s*(\S+)/i);
  if (sigmaMatch) return `sigma: ${sigmaMatch[1]}`;
  const mitreTechnique = msg.match(/\[T\d{4}(?:\.\d{3})?\]/);
  if (mitreTechnique) return mitreTechnique[0];
  return null;
}

// ---------------------------------------------------------------------------
// Entity chips (for expanded panel)
// ---------------------------------------------------------------------------

const MAX_CHIPS = 3;

function flatEntities(es: LiveEvent["entity_summary"]): string[] {
  return Object.values(es ?? {}).flatMap((v) => v ?? []);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function EventRowImpl({ event, expanded, onToggle }: Props): JSX.Element {
  const level = sevLevel(event.severity_id);
  const ts = useMemo(() => fmtTs(event.timestamp_ns), [event.timestamp_ns]);
  const truncatedMsg = event.message.length > MAX_MSG
    ? event.message.slice(0, MAX_MSG) + "…"
    : event.message;
  const { sigma, killChain, anomaly } = useMemo(() => detectTags(event), [event]);
  const entities = useMemo(() => flatEntities(event.entity_summary), [event.entity_summary]);
  const visibleChips = entities.slice(0, MAX_CHIPS);
  const overflow = Math.max(0, entities.length - MAX_CHIPS);

  return (
    <div
      role="button"
      aria-label="event row"
      tabIndex={0}
      data-severity={level}
      onClick={() => onToggle(event.event_id)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          onToggle(event.event_id);
        } else if (e.key === " ") {
          e.preventDefault();
          onToggle(event.event_id);
        }
      }}
      style={{
        display: "grid",
        gridTemplateColumns: "110px 50px 60px 130px 110px 1fr",
        gap: "14px",
        padding: "6px 24px",
        borderBottom: "1px solid var(--line)",
        background: rowBackground(level),
        alignItems: "baseline",
        cursor: "pointer",
        fontFamily: "var(--font-mono)",
        fontSize: "11.5px",
      }}
    >
      {/* timestamp */}
      <span className="sf-tnum" style={{ color: "var(--text-3)" }}>{ts}</span>

      {/* level */}
      <span
        data-testid="col-level"
        style={{
          color: sevColor(level),
          fontWeight: level !== "info" && level !== "mute" ? 600 : 400,
        }}
      >
        {event.severity_text || event.severity_id}
      </span>

      {/* source */}
      <span data-testid="col-source" style={{ color: "var(--text-3)" }}>
        {event.source_type}
      </span>

      {/* host — from entity_summary.hosts[0] or a placeholder */}
      <span
        data-col="host"
        style={{ color: "var(--accent)" }}
      >
        {event.entity_summary?.hosts?.[0] ?? "—"}
      </span>

      {/* logger — template_id as proxy */}
      <span style={{ color: "var(--text-3)" }}>
        {`tpl:${event.template_id}`}
      </span>

      {/* message + tags */}
      <span
        data-testid="event-message"
        style={{
          color: sigma || killChain || anomaly ? "var(--text)" : "var(--text-2)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          display: "flex",
          alignItems: "baseline",
          gap: 8,
        }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", flex: 1 }} title={event.message}>
          {truncatedMsg}
        </span>
        {sigma && (
          <SFBadge variant="warn">{sigma}</SFBadge>
        )}
        {killChain && (
          <SFBadge variant="crit">kill_chain</SFBadge>
        )}
        {anomaly && !killChain && (
          <SFBadge variant="accent">anomaly</SFBadge>
        )}
      </span>

      {/* Expanded detail panel */}
      {expanded && (
        <div
          style={{
            gridColumn: "1 / -1",
            display: "grid",
            gridTemplateColumns: "auto 1fr",
            gap: "4px 12px",
            padding: "8px",
            fontSize: 11,
            background: "var(--surface-2)",
            borderRadius: 2,
          }}
        >
          <dt className="sf-mono" style={{ fontWeight: 600 }}>message</dt>
          <dd className="sf-mono">{event.message}</dd>
          <dt className="sf-mono" style={{ fontWeight: 600 }}>template_id</dt>
          <dd>{event.template_id}</dd>
          <dt className="sf-mono" style={{ fontWeight: 600 }}>observed_ns</dt>
          <dd>{String(event.observed_ns)}</dd>
          {Object.entries(event.entity_summary ?? {}).map(([k, vs]) => (
            <span key={k} className="contents">
              <dt className="sf-mono" style={{ fontWeight: 600 }}>{k}</dt>
              <dd>{vs?.join(", ")}</dd>
            </span>
          ))}
          {typeof event.score === "number" && (
            <>
              <dt className="sf-mono" style={{ fontWeight: 600 }}>score</dt>
              <dd>{event.score.toFixed(3)}</dd>
            </>
          )}
          {event.is_anomaly && (
            <>
              <dt className="sf-mono" style={{ fontWeight: 600 }}>anomaly</dt>
              <dd style={{ color: "var(--crit)" }}>true</dd>
            </>
          )}
          {/* entity chips for overflow display */}
          {visibleChips.length > 0 && (
            <>
              <dt className="sf-mono" style={{ fontWeight: 600 }}>entities</dt>
              <dd>
                {visibleChips.map((v) => (
                  <span key={v} style={{ marginRight: 4, fontSize: 10 }}>{v}</span>
                ))}
                {overflow > 0 && <span>+{overflow}</span>}
              </dd>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export const EventRow = memo(EventRowImpl, (a, b) =>
  a.event.event_id === b.event.event_id && a.expanded === b.expanded,
);
