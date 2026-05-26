import { useState } from "react";
import { intensityLevel, INTENSITY_STYLE } from "./intensity";

export interface TechniqueCellProps {
  tactic: string;
  technique: string;
  name: string;
  ruleCount: number;
  alertCount: number;
  ruleNames: string[];
  covered: boolean;
  detected: boolean;
  onOpen?: (tactic: string, technique: string) => void;
}

function status(covered: boolean, detected: boolean): "Detected" | "Covered" | "Gap" {
  if (covered && detected) return "Detected";
  if (covered) return "Covered";
  return "Gap";
}

export function TechniqueCell({
  tactic,
  technique,
  name,
  ruleCount,
  alertCount,
  ruleNames,
  covered,
  detected,
  onOpen,
}: TechniqueCellProps) {
  const [hovered, setHovered] = useState(false);
  const intensity = intensityLevel(covered, detected, ruleCount, alertCount);
  const title = `${technique} — ${name}`;
  const label = `${technique} ${name} — ${status(covered, detected)}, ${ruleCount} rules, ${alertCount} alerts`;

  function fire() {
    setHovered(false);
    onOpen?.(tactic, technique);
  }

  return (
    <button
      type="button"
      aria-label={label}
      title={title}
      data-intensity={intensity}
      onClick={fire}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onBlur={() => setHovered(false)}
      style={INTENSITY_STYLE[intensity]}
      className="relative h-7 w-full cursor-pointer rounded-sm border-0 p-0 m-0 appearance-none transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      {hovered && (
        <div
          role="tooltip"
          className="absolute bottom-full left-1/2 z-50 mb-2 w-64 -translate-x-1/2 rounded-md border border-zinc-200 bg-white p-3 text-xs text-left shadow-lg dark:border-zinc-700 dark:bg-zinc-900"
        >
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
    </button>
  );
}
