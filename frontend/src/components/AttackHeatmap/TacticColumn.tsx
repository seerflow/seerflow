import { TechniqueCell } from "./TechniqueCell";

interface TechniqueEntry {
  id: string;
  name: string;
  ruleCount: number;
  alertCount: number;
  ruleNames: string[];
  covered: boolean;
  detected: boolean;
}

interface TacticColumnProps {
  tacticName: string;
  techniques: TechniqueEntry[];
}

export function TacticColumn({ tacticName, techniques }: TacticColumnProps) {
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
          technique={t.id}
          name={t.name}
          ruleCount={t.ruleCount}
          alertCount={t.alertCount}
          ruleNames={t.ruleNames}
          covered={t.covered}
          detected={t.detected}
        />
      ))}
    </div>
  );
}
