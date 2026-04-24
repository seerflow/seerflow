import { useEntityStore } from "@/stores/entity";
import { navigateToEntity } from "@/lib/hash";
import { EntityTimelineList } from "./EntityTimelineList";
import { RelatedEntitiesPanel } from "./RelatedEntitiesPanel";
import { EntityGraph } from "./EntityGraph";
import { RiskSparkline } from "./RiskSparkline";
import type { TimelineRange } from "@/lib/types";

const RANGES: TimelineRange[] = ["1h", "6h", "24h", "7d"];

export function EntityDetail() {
  const uuid = useEntityStore((s) => s.selectedEntityUuid);
  const range = useEntityStore((s) => s.range);
  const events = useEntityStore((s) => s.events);
  const related = useEntityStore((s) => s.related);
  const total = useEntityStore((s) => s.total);
  const loading = useEntityStore((s) => s.loading);
  const setRange = useEntityStore((s) => s.setRange);
  const riskHistory = useEntityStore((s) => s.riskHistory);
  const riskHistoryLoading = useEntityStore((s) => s.riskHistoryLoading);
  const riskHistoryError = useEntityStore((s) => s.riskHistoryError);

  const selectedType = useEntityStore((s) => s.selectedEntityType);
  const selectedValue = useEntityStore((s) => s.selectedEntityValue);

  function navigate(toUuid: string) {
    navigateToEntity(toUuid);
  }

  if (!uuid) return null;

  const focalLabel = selectedValue ?? related[0]?.entity_value ?? uuid.slice(0, 8);
  const focalType = selectedType ?? related[0]?.entity_type ?? "user";

  return (
    <section className="flex flex-col gap-3 h-full min-h-0" aria-label="Entity detail">
      <header className="flex items-baseline gap-3">
        <h2 className="font-mono text-lg">{focalLabel}</h2>
        <span className="text-xs text-muted-foreground">…{uuid.slice(-12)}</span>
        <RiskSparkline
          data={riskHistory}
          loading={riskHistoryLoading}
          error={riskHistoryError}
          range={range}
          label={focalLabel}
        />
      </header>
      <div className="flex gap-2" role="toolbar" aria-label="Time range">
        {RANGES.map((r) => (
          <button
            key={r}
            aria-pressed={range === r}
            onClick={() => void setRange(r)}
            className={`rounded px-2 py-1 text-xs ${range === r ? "bg-primary text-primary-foreground" : "border"}`}
          >
            {r}
          </button>
        ))}
      </div>
      {loading === "loading-detail" && events.length === 0 && (
        <div role="status" aria-label="Loading timeline" className="h-40 animate-pulse rounded border bg-muted/20" />
      )}
      <div className="grid gap-3 lg:grid-cols-[1fr_280px]">
        <div className="min-h-[320px] rounded-md border">
          <EntityTimelineList events={events} total={total} limit={1000} />
        </div>
        <RelatedEntitiesPanel related={related} onNavigate={navigate} />
      </div>
      <EntityGraph
        focal={{ uuid, label: focalLabel, type: focalType }}
        related={related}
        onNavigate={navigate}
      />
    </section>
  );
}
