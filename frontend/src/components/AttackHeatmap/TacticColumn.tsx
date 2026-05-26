import { MonoLabel } from "@/components/ui/primitives";
import { TechniqueCell } from "./TechniqueCell";
import type { MergedTechnique } from "./types";

export interface TacticColumnProps {
  tacticId: string;
  tacticShortname: string;
  tacticName: string;
  techniques: MergedTechnique[];
  onOpen?: (tactic: string, technique: string) => void;
}

export function TacticColumn({
  tacticId,
  tacticShortname,
  tacticName,
  techniques,
  onOpen,
}: TacticColumnProps) {
  return (
    <div className="flex flex-col min-w-0">
      <div className="px-1 pb-2">
        <MonoLabel className="text-[9px] tracking-[0.08em]">{tacticId}</MonoLabel>
        <div
          className="text-[11px] font-semibold leading-tight mt-0.5 truncate"
          style={{ color: "var(--text)" }}
          title={tacticName}
        >
          {tacticName}
        </div>
        <MonoLabel className="sf-tnum text-[10px] mt-0.5">
          {techniques.length} technique{techniques.length !== 1 ? "s" : ""}
        </MonoLabel>
      </div>
      <div className="flex flex-col gap-[3px]">
        {techniques.map((t) => (
          <TechniqueCell
            key={t.id}
            tactic={tacticShortname}
            technique={t.id}
            name={t.name}
            ruleCount={t.ruleCount}
            alertCount={t.alertCount}
            ruleNames={t.ruleNames}
            covered={t.covered}
            detected={t.detected}
            onOpen={onOpen}
          />
        ))}
      </div>
    </div>
  );
}
