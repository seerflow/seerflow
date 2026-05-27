import React from "react";
import { cn } from "@/lib/utils";
import { KILL_CHAIN_STAGES } from "./killChainStages";

export { KILL_CHAIN_STAGES } from "./killChainStages";
export type { KillChainStageDefinition } from "./killChainStages";

export type KillChainStageState = "done" | "active" | "imminent" | "pending";

export interface KillChainStageData {
  relativeTime?: string;
}

const STATE_CLASSES: Record<KillChainStageState, string> = {
  done:     "border-info  text-info   bg-[color-mix(in_oklch,var(--info)_8%,transparent)]",
  active:   "border-crit  text-crit   bg-[color-mix(in_oklch,var(--crit)_12%,transparent)]",
  imminent: "border-warn  text-warn   bg-[color-mix(in_oklch,var(--warn)_8%,transparent)]",
  pending:  "border-line  text-text-3 bg-surface-2",
};

const DOT_CLASSES: Record<KillChainStageState, string> = {
  done:     "bg-info",
  active:   "bg-crit",
  imminent: "bg-warn",
  pending:  "bg-surface-2 border border-line",
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
  /** Per-stage runtime data (relativeTime, etc.). Length may be < 7. */
  stages: KillChainStageData[];
  className?: string;
}

/**
 * Kill-chain timeline — 7 MITRE ATT&CK stages with done/active/imminent/pending states.
 * Vertical layout; sharp geometry (no rounded corners per §3.7).
 */
export const KillChain: React.FC<KillChainProps> = ({ activeIdx, stages, className }) => (
  <ol
    role="list"
    aria-label="kill chain"
    className={cn("flex flex-col gap-0", className)}
  >
    {KILL_CHAIN_STAGES.map((def, idx) => {
      const state = stateFor(idx, activeIdx);
      const stageData = stages[idx];
      const isLast = idx === KILL_CHAIN_STAGES.length - 1;

      return (
        <li
          key={def.taId}
          data-testid={`kc-stage-${state}`}
          aria-current={state === "active" ? "step" : undefined}
          className="relative flex items-start gap-3 pb-0"
        >
          {/* Connector line */}
          {!isLast && (
            <div
              aria-hidden="true"
              className={cn(
                "absolute left-[7px] top-4 w-px",
                state === "done" ? "bg-info h-full" : "bg-line h-full",
              )}
              style={{ height: "calc(100% + 8px)" }}
            />
          )}

          {/* Stage dot */}
          <div
            aria-hidden="true"
            className={cn(
              "relative z-10 mt-1 flex-shrink-0 rounded-full",
              "w-[15px] h-[15px]",
              DOT_CLASSES[state],
            )}
          />

          {/* Stage label card */}
          <div
            className={cn(
              "mb-2 flex-1 border px-3 py-2",
              STATE_CLASSES[state],
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="sf-mono text-[10px] opacity-70">{def.taId}</span>
                <span className="text-xs font-medium">{def.label}</span>
              </div>
              {stageData?.relativeTime && (
                <span className="sf-mono text-[10px] opacity-70 flex-shrink-0">
                  {stageData.relativeTime}
                </span>
              )}
            </div>
          </div>
        </li>
      );
    })}
  </ol>
);
