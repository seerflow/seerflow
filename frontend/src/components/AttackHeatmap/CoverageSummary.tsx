import { cn } from "@/lib/utils";
import { Stat } from "@/components/ui/primitives";

interface CoverageSummaryProps {
  detectedTactics: number;
  criticalHeat: number;
  ruleCoveragePct: number;
  mlOnlyDetections: number;
}

interface StatEntry {
  label: string;
  value: string;
}

export function CoverageSummary({
  detectedTactics,
  criticalHeat,
  ruleCoveragePct,
  mlOnlyDetections,
}: CoverageSummaryProps) {
  const stats: StatEntry[] = [
    { label: "detected tactics", value: String(detectedTactics) },
    { label: "critical heat", value: String(criticalHeat) },
    { label: "rule coverage", value: `${ruleCoveragePct}%` },
    { label: "ml-only detections", value: String(mlOnlyDetections) },
  ];

  return (
    <div
      data-testid="coverage-summary"
      className="grid grid-cols-4 mt-7"
      style={{ border: "1px solid var(--line)" }}
    >
      {stats.map((s, i) => (
        <div
          key={s.label}
          className={cn("px-[18px] py-[14px]", i < 3 && "border-r")}
          style={{
            background: "var(--surface)",
            borderColor: "var(--line)",
          }}
        >
          <Stat label={s.label} value={s.value} />
        </div>
      ))}
    </div>
  );
}
