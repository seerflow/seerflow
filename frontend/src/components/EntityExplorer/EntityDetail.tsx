import { useEntityStore } from "@/stores/entity";
import { navigateToEntity } from "@/lib/hash";
import { EntityTimelineList } from "./EntityTimelineList";
import { RelatedEntitiesPanel } from "./RelatedEntitiesPanel";
import { EntityGraph } from "./EntityGraph";
import { RiskSparkline } from "./RiskSparkline";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { entitySourceColor } from "@/lib/entitySourceColor";
import { SEVERITY_NUM_LABEL } from "@/lib/severity";
import { useToast } from "@/hooks/useToast";
import { Copy } from "lucide-react";
import type { TimelineRange } from "@/lib/types";

const RANGES: TimelineRange[] = ["1h", "6h", "24h", "7d"];
const SEVERITY_LEVELS = [0, 1, 2, 3, 4, 5, 6] as const;

export function EntityDetail() {
  const uuid = useEntityStore((s) => s.selectedEntityUuid);
  const range = useEntityStore((s) => s.range);
  const events = useEntityStore((s) => s.events);
  const related = useEntityStore((s) => s.related);
  const total = useEntityStore((s) => s.total);
  const loading = useEntityStore((s) => s.loading);
  const setRange = useEntityStore((s) => s.setRange);
  const sourceFilter = useEntityStore((s) => s.sourceFilter);
  const severityMin = useEntityStore((s) => s.severityMin);
  const discoveredSourceTypes = useEntityStore((s) => s.discoveredSourceTypes);
  const setSourceFilter = useEntityStore((s) => s.setSourceFilter);
  const setSeverityMin = useEntityStore((s) => s.setSeverityMin);
  const riskHistory = useEntityStore((s) => s.riskHistory);
  const riskHistoryLoading = useEntityStore((s) => s.riskHistoryLoading);
  const riskHistoryError = useEntityStore((s) => s.riskHistoryError);

  const selectedType = useEntityStore((s) => s.selectedEntityType);
  const selectedValue = useEntityStore((s) => s.selectedEntityValue);

  const toast = useToast();

  function navigate(toUuid: string) {
    navigateToEntity(toUuid);
  }

  async function copyUuid() {
    if (!uuid) return;
    try {
      await navigator.clipboard.writeText(uuid);
      toast.success("Copied UUID");
    } catch {
      toast.error("Copy failed");
    }
  }

  function onSourceChange(value: string) {
    void setSourceFilter(value === "__all__" ? null : value);
  }

  function onSeverityChange(value: string) {
    if (!value) return;
    const n = Number(value);
    void setSeverityMin(n === 0 ? null : n);
  }

  if (!uuid) return null;

  const focalLabel = selectedValue ?? related[0]?.entity_value ?? uuid.slice(0, 8);
  const focalType = selectedType ?? related[0]?.entity_type ?? "user";

  return (
    <section className="flex flex-col gap-3 h-full min-h-0" aria-label="Entity detail">
      <header className="flex items-baseline gap-3">
        {selectedType ? (
          <Badge
            style={{ backgroundColor: entitySourceColor("type:" + selectedType), color: "white" }}
          >
            {selectedType.toUpperCase()}
          </Badge>
        ) : (
          <Badge variant="outline">—</Badge>
        )}
        <h2 className="font-mono text-lg">{focalLabel}</h2>
        <button
          type="button"
          onClick={copyUuid}
          aria-label="Copy entity UUID"
          title={uuid}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-accent"
        >
          …{uuid.slice(-12)}
          <Copy className="h-3 w-3" aria-hidden="true" />
        </button>
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
            type="button"
            aria-pressed={range === r}
            onClick={() => void setRange(r)}
            className={`rounded px-2 py-1 text-xs ${range === r ? "bg-primary text-primary-foreground" : "border"}`}
          >
            {r}
          </button>
        ))}
        <button
          type="button"
          disabled
          aria-disabled="true"
          title="Coming soon"
          className="rounded border px-2 py-1 text-xs text-muted-foreground opacity-60"
        >
          Custom…
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">Source</span>
          <Select value={sourceFilter ?? "__all__"} onValueChange={onSourceChange}>
            <SelectTrigger aria-label="Source" className="h-7 w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">All sources</SelectItem>
              {discoveredSourceTypes.map((s) => (
                <SelectItem key={s} value={s}>{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">Severity</span>
          <ToggleGroup
            type="single"
            value={String(severityMin ?? 0)}
            onValueChange={onSeverityChange}
            aria-label="Severity minimum"
          >
            {SEVERITY_LEVELS.map((n) => (
              <ToggleGroupItem
                key={n}
                value={String(n)}
                aria-label={SEVERITY_NUM_LABEL[n]}
                className="h-7 px-2 text-xs"
              >
                {n}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </label>
      </div>
      {loading === "loading-detail" && events.length === 0 && (
        <div role="status" aria-label="Loading timeline" className="h-40 animate-pulse rounded border bg-muted/20" />
      )}
      <div className="grid flex-1 min-h-0 gap-3 lg:grid-cols-[1fr_280px]">
        <div className="h-full min-h-0 overflow-hidden rounded-md border flex flex-col">
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
