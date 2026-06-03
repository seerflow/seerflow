import React from "react";
import { EntityGlyph, RiskBar, riskLevelFromValue } from "@/components/ui/primitives";
import type { EntityType } from "@/components/ui/primitives";

export interface RiskEntity {
  id: string;
  name: string;
  /** Entity kind string — mapped to EntityType for the glyph. */
  kind: string;
  /** Risk score 0–1. */
  risk: number;
  eventCount: number;
  alertCount: number;
}

export interface TopRiskEntitiesProps {
  entities: RiskEntity[];
}

const VALID_ENTITY_TYPES: EntityType[] = ["user", "host", "ip", "service", "process"];

function toEntityType(kind: string): EntityType {
  const lower = kind.toLowerCase();
  if ((VALID_ENTITY_TYPES as string[]).includes(lower)) return lower as EntityType;
  return "host";
}

const RISK_COLORS: Record<string, string> = {
  crit:   "var(--crit)",
  warn:   "var(--warn)",
  accent: "var(--text-2)",
  mute:   "var(--text-3)",
};

/**
 * Top risk entities right-column panel.
 * EntityGlyph + name/kind + risk score + RiskBar + events/alerts count.
 */
export const TopRiskEntities: React.FC<TopRiskEntitiesProps> = ({ entities }) => (
  <div style={{ display: "flex", flexDirection: "column" }}>
    {/* Header */}
    <div
      style={{
        padding: "18px 24px",
        borderBottom: "1px solid var(--line)",
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 600 }}>Top risk entities</div>
      <span className="sf-mono" style={{ fontSize: 11, color: "var(--text-3)" }}>
        last 24h
      </span>
    </div>

    {/* Entity list */}
    <div style={{ flex: 1, overflow: "hidden" }}>
      {entities.length === 0 ? (
        <div
          data-testid="top-entities-empty"
          className="sf-mono"
          style={{
            padding: "24px",
            fontSize: 12,
            color: "var(--text-3)",
            textAlign: "center",
          }}
        >
          No entities tracked yet.
        </div>
      ) : (
        entities.map((entity, i) => {
          const level = riskLevelFromValue(entity.risk);
          const riskColor = RISK_COLORS[level] ?? "var(--text-2)";
          const entityType = toEntityType(entity.kind);

          return (
            <div
              key={entity.id}
              data-testid={`entity-row-${entity.id}`}
              style={{
                padding: "12px 24px",
                borderBottom: i < entities.length - 1 ? "1px solid var(--line)" : 0,
              }}
            >
              {/* Name + glyph row */}
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <EntityGlyph type={entityType} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    className="sf-mono"
                    style={{
                      fontSize: 12.5,
                      color: "var(--text)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {entity.name}
                  </div>
                  <div
                    data-testid={`entity-kind-${entity.id}`}
                    className="sf-mono"
                    style={{
                      fontSize: 10.5,
                      color: "var(--text-3)",
                      marginTop: 1,
                      letterSpacing: "0.06em",
                      textTransform: "uppercase",
                    }}
                  >
                    {entity.kind}
                  </div>
                </div>
                <span
                  data-testid={`risk-score-${entity.id}`}
                  data-level={level}
                  className="sf-mono sf-tnum"
                  style={{ fontSize: 11.5, color: riskColor }}
                >
                  {entity.risk.toFixed(2)}
                </span>
              </div>

              {/* Risk bar + counts */}
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
                <RiskBar value={entity.risk} height={3} className="flex-1" />
                <span
                  className="sf-mono sf-tnum"
                  style={{ fontSize: 10.5, color: "var(--text-3)", minWidth: 60, textAlign: "right" }}
                >
                  {entity.eventCount.toLocaleString()} ev · {entity.alertCount}a
                </span>
              </div>
            </div>
          );
        })
      )}
    </div>
  </div>
);
