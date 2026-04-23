import { useEffect } from "react";
import { useCoverageStore } from "@/stores/coverage";
import { TacticColumn } from "./TacticColumn";
import { CoverageSummary } from "./CoverageSummary";
import catalog from "@/data/attack-enterprise.json";
import type { AttackCoverageResponse } from "@/lib/types";

interface MergedTechnique {
  id: string;
  name: string;
  ruleCount: number;
  alertCount: number;
  ruleNames: string[];
  covered: boolean;
  detected: boolean;
}

interface MergedTactic {
  id: string;
  shortname: string;
  name: string;
  techniques: MergedTechnique[];
}

/**
 * Merge API coverage response with the static ATT&CK catalog.
 *
 * Known limitation: the static catalog contains only top-level technique IDs
 * (e.g. T1053). Sub-technique IDs returned by the backend (e.g. T1053.005)
 * will not match any catalog entry and render as gap cells even when rules
 * cover them. This is a known gap tracked for future iteration — rolling up
 * sub-techniques into parents at the backend is the preferred fix.
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
  const detectedCount = merged.reduce(
    (s, t) => s + t.techniques.filter((te) => te.detected).length,
    0,
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-4 flex items-center gap-3">
        <a
          href="#"
          className="text-sm text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
        >
          ← Dashboard
        </a>
        <h2 className="text-lg font-semibold">ATT&amp;CK Coverage Matrix</h2>
      </div>
      <CoverageSummary
        totalTechniques={totalTechs}
        coveredCount={coveredCount}
        detectedCount={detectedCount}
        totalRules={data.summary.total_rules_with_attack_tags}
        totalAlerts={data.summary.total_alerts_matched}
        windowSince={data.window_since}
        windowUntil={data.window_until}
      />
      <div className="flex min-h-0 flex-1 gap-1 overflow-x-auto pb-4">
        {merged.map((tactic) => (
          <TacticColumn
            key={tactic.id}
            tacticShortname={tactic.shortname}
            tacticName={tactic.name}
            techniques={tactic.techniques}
          />
        ))}
      </div>
      <div className="mt-3 flex items-center gap-4 text-xs text-zinc-500">
        <span className="inline-flex items-center gap-1">
          <span className="cell-detected inline-block h-3 w-3 rounded-sm" />{" "}
          Covered + Detected
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="cell-covered inline-block h-3 w-3 rounded-sm" />{" "}
          Covered
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="cell-gap inline-block h-3 w-3 rounded-sm" /> No
          Coverage
        </span>
      </div>
    </div>
  );
}
