import { TechniqueCell } from "./TechniqueCell";
import type { MergedTechnique } from "./types";

export interface TacticColumnProps {
  tacticShortname: string;
  tacticName: string;
  techniques: MergedTechnique[];
  onOpen?: (tactic: string, technique: string) => void;
}

export function TacticColumn({
  tacticShortname,
  tacticName,
  techniques,
  onOpen,
}: TacticColumnProps) {
  return (
    <div className="flex min-w-[7rem] flex-col items-center gap-0.5">
      <h3
        className="mb-1 max-w-[7rem] truncate text-center text-[10px] font-medium text-zinc-600 dark:text-zinc-400"
        title={tacticName}
      >
        {tacticName}
      </h3>
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
  );
}
