import { useEffect } from "react";
import { useCoverageStore } from "@/stores/coverage";
import { useDrilldownStore } from "@/stores/drilldown";
import { MonoLabel } from "@/components/ui/primitives";
import { TacticColumn } from "./TacticColumn";
import { CoverageSummary } from "./CoverageSummary";
import { DrilldownPanel } from "./DrilldownPanel";
import catalog from "@/data/attack-enterprise.json";
import type { AttackCoverageResponse } from "@/lib/types";
import type { MergedTactic } from "./types";
import { INTENSITY_STYLE, INTENSITY_SWATCHES } from "./intensity";

/**
 * Merge API coverage response with the static ATT&CK catalog.
 *
 * The static catalog stays parent-only by contract (no sub-technique entries).
 * The backend rolls sub-technique IDs (e.g. T1053.005) into their parent
 * (T1053) before returning, so every cell here matches a catalog entry.
 */
function mergeCatalog(apiData: AttackCoverageResponse): MergedTactic[] {
  const cellMap = new Map<
    string,
    {
      rule_count: number;
      alert_count: number;
      rule_names: string[];
      covered: boolean;
      detected: boolean;
    }
  >();

  for (const tactic of apiData.tactics) {
    for (const cell of tactic.techniques) {
      cellMap.set(`${tactic.tactic}:${cell.technique}`, cell);
    }
  }

  return catalog.tactics.map((tactic) => ({
    id: tactic.id,
    shortname: tactic.shortname,
    name: tactic.name,
    techniques: tactic.techniques.map((tech) => {
      const cell = cellMap.get(`${tactic.shortname}:${tech.id}`);
      return {
        id: tech.id,
        name: tech.name,
        ruleCount: cell?.rule_count ?? 0,
        alertCount: cell?.alert_count ?? 0,
        ruleNames: cell?.rule_names ?? [],
        covered: cell?.covered ?? false,
        detected: cell?.detected ?? false,
      };
    }),
  }));
}

function totalTechniqueCount(): number {
  return catalog.tactics.reduce((sum, t) => sum + t.techniques.length, 0);
}

export function AttackHeatmap() {
  const data = useCoverageStore((s) => s.data);
  const loading = useCoverageStore((s) => s.loading);
  const error = useCoverageStore((s) => s.error);
  const fetch = useCoverageStore((s) => s.fetch);

  useEffect(() => {
    void fetch();
  }, [fetch]);

  if (loading) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center text-zinc-500">
        Loading coverage data…
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center text-red-500">
        {error}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center text-zinc-500">
        No coverage data available.
      </div>
    );
  }

  const merged = mergeCatalog(data);
  const totalTechs = totalTechniqueCount();
  const coveredCount = merged.reduce(
    (s, t) => s + t.techniques.filter((te) => te.covered).length,
    0,
  );

  const detectedTactics = merged.filter(
    (t) => t.techniques.some((te) => te.detected),
  ).length;
  const criticalHeat = merged.filter(
    (t) => t.techniques.some((te) => te.detected && te.alertCount > 0),
  ).length;
  const ruleCoveragePct =
    totalTechs > 0 ? Math.round((coveredCount / totalTechs) * 100) : 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header band */}
      <div
        className="flex items-center px-6 py-[14px] gap-3 flex-shrink-0"
        style={{ borderBottom: "1px solid var(--line)" }}
      >
        <span className="text-sm font-semibold">Coverage heatmap</span>
        <MonoLabel>
          · {merged.length} tactics · {totalTechs} techniques ·{" "}
          {data.summary.total_rules_with_attack_tags} sigma rules
        </MonoLabel>
        <span className="flex-1" />
        {/* Intensity legend */}
        <div className="flex items-center gap-2">
          <MonoLabel className="text-[10px]">intensity</MonoLabel>
          {INTENSITY_SWATCHES.map(({ level }) => (
            <span
              key={level}
              data-intensity-swatch={level}
              style={{ width: 14, height: 14, flexShrink: 0, ...INTENSITY_STYLE[level] }}
            />
          ))}
        </div>
      </div>

      {/* Scrollable grid area */}
      <div className="flex-1 min-h-0 overflow-auto px-6 pb-6 pt-4">
        {/* Tactic columns grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${merged.length}, 1fr)`,
            gap: 4,
          }}
        >
          {merged.map((tactic) => (
            <TacticColumn
              key={tactic.id}
              tacticId={tactic.id}
              tacticShortname={tactic.shortname}
              tacticName={tactic.name}
              techniques={tactic.techniques}
              onOpen={(t, T) => useDrilldownStore.getState().open(t, T)}
            />
          ))}
        </div>

        <CoverageSummary
          detectedTactics={detectedTactics}
          criticalHeat={criticalHeat}
          ruleCoveragePct={ruleCoveragePct}
          mlOnlyDetections={data.summary.total_alerts_matched}
        />
      </div>

      <DrilldownPanel
        matrix={merged}
        coverageWindow={{ since: data.window_since, until: data.window_until }}
      />
    </div>
  );
}
