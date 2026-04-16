import { useState } from "react";

interface TechniqueCellProps {
  tactic: string;
  technique: string;
  name: string;
  ruleCount: number;
  alertCount: number;
  ruleNames: string[];
  covered: boolean;
  detected: boolean;
}

function cellClass(covered: boolean, detected: boolean): string {
  if (covered && detected) return "cell-detected";
  if (covered) return "cell-covered";
  return "cell-gap";
}

export function TechniqueCell({
  technique,
  name,
  ruleCount,
  alertCount,
  ruleNames,
  covered,
  detected,
}: TechniqueCellProps) {
  const [hovered, setHovered] = useState(false);
  const cls = cellClass(covered, detected);
  const title = `${technique} — ${name}`;

  return (
    <div
      className={`${cls} relative h-6 w-6 cursor-pointer rounded-sm transition-colors`}
      title={title}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {hovered && (
        <div className="absolute bottom-full left-1/2 z-50 mb-2 w-64 -translate-x-1/2 rounded-md border border-zinc-200 bg-white p-3 text-xs shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
          <p className="mb-1 font-semibold">{title}</p>
          <hr className="mb-1 border-zinc-200 dark:border-zinc-700" />
          {covered ? (
            <>
              <p>Rules: {ruleCount}</p>
              <ul className="ml-3 list-disc">
                {ruleNames.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
              <p className="mt-1">Alerts (window): {alertCount}</p>
            </>
          ) : (
            <p className="italic text-zinc-500">No rules loaded for this technique.</p>
          )}
        </div>
      )}
    </div>
  );
}
