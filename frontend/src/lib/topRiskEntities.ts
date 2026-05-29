/**
 * Derive the Overview "Top risk entities" list from the live alert store.
 *
 * The dashboard has no dedicated top-entities endpoint yet, but alerts already
 * carry the entity they fired on plus a risk score, so the roll-up can be
 * computed client-side: group alerts by entity, take the peak risk, sum the
 * deduped event counts, and rank. Pure + side-effect free for easy testing.
 */
import type { Alert } from "@/lib/types";
import type { RiskEntity } from "@/components/Overview/TopRiskEntities";

const TOP_N = 7;

export function deriveTopRiskEntities(alerts: readonly Alert[]): RiskEntity[] {
  const byUuid = new Map<string, RiskEntity>();

  for (const a of alerts) {
    if (!a.entity_uuid || !a.entity_value) continue;
    const existing = byUuid.get(a.entity_uuid);
    if (!existing) {
      byUuid.set(a.entity_uuid, {
        id: a.entity_uuid,
        name: a.entity_value,
        kind: a.entity_type ?? "host",
        risk: a.risk_score,
        eventCount: a.dedup_count,
        alertCount: 1,
      });
      continue;
    }
    // Keep the highest-risk alert's name/kind so the label tracks the worst hit.
    const next: RiskEntity = {
      ...existing,
      risk: Math.max(existing.risk, a.risk_score),
      eventCount: existing.eventCount + a.dedup_count,
      alertCount: existing.alertCount + 1,
    };
    if (a.risk_score > existing.risk) {
      next.name = a.entity_value;
      next.kind = a.entity_type ?? "host";
    }
    byUuid.set(a.entity_uuid, next);
  }

  return [...byUuid.values()]
    .sort((x, y) => (y.risk === x.risk ? y.alertCount - x.alertCount : y.risk - x.risk))
    .slice(0, TOP_N);
}
