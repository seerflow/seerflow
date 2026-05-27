import React from "react";
import { cn } from "@/lib/utils";
import { KILL_CHAIN_STAGES } from "./killChainStages";

export { KILL_CHAIN_STAGES } from "./killChainStages";
export type { KillChainStageDefinition } from "./killChainStages";

export type KillChainStageState = "done" | "active" | "imminent" | "pending";

export interface KillChainStageData {
  /** Relative time for the stage, e.g. "−12m" / "5m ago". */
  relativeTime?: string;
  /** Per-stage detail sub-label, e.g. "ssh_brute_force". */
  label?: string;
}

/** State → top rule-bar + sub-label color (mockup `DashAlertDetail` KillChain). */
const STATE_COLOR: Record<KillChainStageState, string> = {
  done:     "var(--text-2)",
  active:   "var(--crit)",
  imminent: "var(--warn)",
  pending:  "var(--text-3)",
};

function stateFor(idx: number, activeIdx: number | undefined): KillChainStageState {
  if (activeIdx === undefined) return "pending";
  if (idx < activeIdx) return "done";
  if (idx === activeIdx) return "active";
  if (idx === activeIdx + 1) return "imminent";
  return "pending";
}

export interface KillChainProps {
  /**
   * Index (0-based) of the currently active stage.
   * Stages before it = done; stage after = imminent; rest = pending.
   * Omit to render all stages as pending.
   */
  activeIdx?: number;
  /** Per-stage runtime data (relativeTime, label, …). Length may be < 7. */
  stages: KillChainStageData[];
  className?: string;
}

/**
 * Kill-chain timeline — 7 MITRE ATT&CK stages with done/active/imminent/pending
 * states, laid out as a horizontal grid to match the `DashAlertDetail` mockup:
 * each cell shows a state-colored top rule, the tac-id + relative-time row, the
 * stage name, and an optional detail sub-label. Sharp geometry (no radius).
 *
 * The `list` / `listitem` roles, `aria-label="kill chain"`, the
 * `kc-stage-{state}` testids and `aria-current="step"` on the active stage are
 * part of the screen + e2e contract and are preserved across the restyle.
 */
export const KillChain: React.FC<KillChainProps> = ({ activeIdx, stages, className }) => (
  <ol
    role="list"
    aria-label="kill chain"
    className={cn("gap-0", className)}
    style={{
      display: "grid",
      gridTemplateColumns: `repeat(${KILL_CHAIN_STAGES.length}, 1fr)`,
    }}
  >
    {KILL_CHAIN_STAGES.map((def, idx) => {
      const state = stateFor(idx, activeIdx);
      const stageData = stages[idx];
      const color = STATE_COLOR[state];

      return (
        <li
          key={def.taId}
          data-testid={`kc-stage-${state}`}
          aria-current={state === "active" ? "step" : undefined}
          className="relative pr-2"
        >
          {/* Top state rule */}
          <div
            aria-hidden="true"
            className="mb-3"
            style={{
              height: 3,
              background: state === "pending" ? "var(--surface-2)" : color,
            }}
          />

          {/* tac-id + relative-time */}
          <div className="flex items-baseline justify-between">
            <span className="sf-mono text-[10px] text-text-3 tracking-[0.06em]">{def.taId}</span>
            {stageData?.relativeTime && (
              <span className="sf-mono sf-tnum text-[10px] text-text-3">
                {stageData.relativeTime}
              </span>
            )}
          </div>

          {/* Stage name */}
          <div
            className={cn(
              "mt-1.5 text-xs font-semibold tracking-[-0.01em]",
              state === "pending" ? "text-text-3" : "text-text",
            )}
          >
            {def.label}
          </div>

          {/* Optional detail sub-label */}
          {stageData?.label && (
            <div className="sf-mono text-[11px] mt-1" style={{ color }}>
              {stageData.label}
            </div>
          )}
        </li>
      );
    })}
  </ol>
);
