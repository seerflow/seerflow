import React from "react";
import type { LiveEvent } from "@/lib/types";
import { SideBlock } from "@/components/ui/primitives/SideBlock";
import { SFBadge } from "@/components/ui/primitives/Badge";
import { EntityGlyph } from "@/components/ui/primitives/EntityGlyph";
import type { EntityType } from "@/components/ui/primitives/EntityGlyph";

interface Props {
  event: LiveEvent | null;
}

// Map entity_summary keys to EntityGlyph types
function toGlyphType(key: string): EntityType {
  if (key === "ips") return "ip";
  if (key === "users") return "user";
  if (key === "hosts") return "host";
  if (key === "processes") return "process";
  return "service";
}

function severityBadgeVariant(id: number): "crit" | "warn" | "info" | "mute" {
  if (id >= 6) return "crit";
  if (id >= 4) return "warn";
  if (id >= 2) return "info";
  return "mute";
}

// Safe JSON serialisation — handles bigint fields by coercing to string
function safeJsonStringify(obj: unknown): string {
  return JSON.stringify(
    obj,
    (_, v) => (typeof v === "bigint" ? String(v) : v),
    2,
  );
}

/**
 * EventInspector — right-rail inspector panel for the Events screen (S-325).
 * Shows four SideBlock sections: Parsed event, Entities extracted,
 * Raw payload, Receiver/pipeline timing.
 */
export const EventInspector: React.FC<Props> = ({ event }) => {
  if (!event) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
          color: "var(--text-3)",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
        }}
      >
        Select an event to inspect
      </div>
    );
  }

  const variant = severityBadgeVariant(event.severity_id);
  const pipelineMs =
    Number((event.observed_ns - event.timestamp_ns) / 1_000_000n);

  const entityEntries = Object.entries(event.entity_summary ?? {});

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      {/* Section 1: Parsed event */}
      <SideBlock title="Parsed event">
        <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <SFBadge
              data-testid="inspector-severity"
              variant={variant}
            >
              {event.severity_text || String(event.severity_id)}
            </SFBadge>
            <span
              style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-3)" }}
            >
              {event.event_id}
            </span>
          </div>
          <p style={{ margin: 0, color: "var(--text-2)", fontSize: 12, lineHeight: 1.5 }}>
            {event.message}
          </p>
        </div>
      </SideBlock>

      {/* Section 2: Entities extracted */}
      <SideBlock title="Entities extracted">
        {entityEntries.length === 0 ? (
          <span style={{ color: "var(--text-3)", fontSize: 11 }}>—</span>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {entityEntries.map(([key, values]) => (
              <div
                key={key}
                data-testid="inspector-entity-row"
                style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}
              >
                <EntityGlyph type={toGlyphType(key)} size={18} />
                {(values ?? []).map((v) => (
                  <span
                    key={v}
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 11,
                      color: "var(--text)",
                    }}
                  >
                    {v}
                  </span>
                ))}
              </div>
            ))}
          </div>
        )}
      </SideBlock>

      {/* Section 3: Raw payload */}
      <SideBlock title="Raw payload">
        <pre
          data-testid="inspector-raw"
          style={{
            margin: 0,
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            color: "var(--text-2)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
            maxHeight: 200,
            overflow: "auto",
          }}
        >
          {safeJsonStringify(event)}
        </pre>
      </SideBlock>

      {/* Section 4: Receiver / pipeline timing */}
      <SideBlock title="Receiver">
        <div style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <span style={{ color: "var(--text-3)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
              source
            </span>
            <span style={{ color: "var(--text)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
              {event.source_type}
            </span>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <span style={{ color: "var(--text-3)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
              pipeline
            </span>
            <span style={{ color: "var(--text)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
              {pipelineMs} ms
            </span>
          </div>
        </div>
      </SideBlock>
    </div>
  );
};
