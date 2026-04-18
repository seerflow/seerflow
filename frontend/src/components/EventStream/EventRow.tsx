import { memo, useMemo } from "react";
import type { LiveEvent } from "@/lib/types";
import { severityIcon } from "@/lib/severityIcon";
import { entitySourceColor } from "@/lib/entitySourceColor";

interface Props {
  event: LiveEvent;
  expanded: boolean;
  onToggle: (eventId: string) => void;
}

const MAX_MSG = 240;
const MAX_CHIPS = 3;

function fmtTs(ns: bigint): string {
  const d = new Date(Number(ns / 1_000_000n));
  const pad = (n: number, w = 2): string => n.toString().padStart(w, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
}

function flatEntities(es: LiveEvent["entity_summary"]): string[] {
  return Object.values(es).flatMap((v) => v ?? []);
}

function EventRowImpl({ event, expanded, onToggle }: Props): JSX.Element {
  const sev = severityIcon(event.severity_id);
  const ts = useMemo(() => fmtTs(event.timestamp_ns), [event.timestamp_ns]);
  const entities = useMemo(() => flatEntities(event.entity_summary), [event.entity_summary]);
  const visibleChips = entities.slice(0, MAX_CHIPS);
  const overflow = Math.max(0, entities.length - MAX_CHIPS);
  const truncatedMsg = event.message.length > MAX_MSG ? event.message.slice(0, MAX_MSG) + "…" : event.message;
  const sourceBg = entitySourceColor(event.source_type);

  return (
    <div
      role="button"
      aria-label="event row"
      tabIndex={0}
      onClick={() => onToggle(event.event_id)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onToggle(event.event_id); }}
      className="flex flex-col gap-1 border-b px-2 py-1 text-xs hover:bg-muted/40 cursor-pointer"
    >
      <div className="flex items-center gap-2">
        <span className="font-mono tabular-nums text-muted-foreground">{ts}</span>
        <span
          className="rounded px-1.5 py-0.5 text-[10px] text-white"
          style={{ backgroundColor: sourceBg }}
        >
          {event.source_type}
        </span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] tone-${sev.tone}`} title={sev.label}>
          <span aria-hidden="true">{sev.emoji}</span> <span>{sev.label}</span>
        </span>
        <span data-testid="event-message" className="truncate flex-1" title={event.message}>
          {truncatedMsg}
        </span>
        {visibleChips.map((v) => (
          <span key={v} className="rounded bg-secondary px-1.5 py-0.5 text-[10px]">{v}</span>
        ))}
        {overflow > 0 && <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px]">+{overflow}</span>}
      </div>
      {expanded && (
        <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 px-2 py-2 text-[11px] bg-muted/30 rounded">
          <dt className="font-semibold">message</dt><dd className="font-mono">{event.message}</dd>
          <dt className="font-semibold">template_id</dt><dd>{event.template_id}</dd>
          <dt className="font-semibold">observed_ns</dt><dd>{String(event.observed_ns)}</dd>
          {Object.entries(event.entity_summary)
            .filter(([k]) => Object.hasOwn(event.entity_summary, k))
            .map(([k, vs]) => (
              <span key={k} className="contents">
                <dt className="font-semibold">{k}</dt><dd>{vs?.join(", ")}</dd>
              </span>
            ))}
          {typeof event.score === "number" && (<><dt className="font-semibold">score</dt><dd>{event.score.toFixed(3)}</dd></>)}
          {event.is_anomaly && <><dt className="font-semibold">anomaly</dt><dd className="text-red-600">true</dd></>}
        </dl>
      )}
    </div>
  );
}

export const EventRow = memo(EventRowImpl, (a, b) =>
  a.event.event_id === b.event.event_id && a.expanded === b.expanded,
);
