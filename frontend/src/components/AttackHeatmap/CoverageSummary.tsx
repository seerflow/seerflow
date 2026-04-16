interface CoverageSummaryProps {
  totalTechniques: number;
  coveredCount: number;
  detectedCount: number;
  totalRules: number;
  totalAlerts: number;
  windowSince: string;
  windowUntil: string;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function CoverageSummary({
  totalTechniques,
  coveredCount,
  detectedCount,
  totalRules,
  totalAlerts,
  windowSince,
  windowUntil,
}: CoverageSummaryProps) {
  const pct =
    totalTechniques > 0
      ? Math.round((coveredCount / totalTechniques) * 100)
      : 0;

  return (
    <div className="mb-4 flex flex-wrap items-center gap-6 rounded-lg border border-zinc-200 bg-zinc-50 px-4 py-3 text-sm dark:border-zinc-700 dark:bg-zinc-900">
      <div>
        <span className="font-semibold">{coveredCount}</span>
        <span className="text-zinc-500">
          /{totalTechniques} techniques covered ({pct}%)
        </span>
      </div>
      <div>
        <span className="font-semibold">{detectedCount}</span>
        <span className="text-zinc-500"> detected (alerts fired)</span>
      </div>
      <div>
        <span className="font-semibold">{totalRules}</span>
        <span className="text-zinc-500"> rule mappings</span>
      </div>
      <div>
        <span className="font-semibold">{totalAlerts}</span>
        <span className="text-zinc-500"> alerts in window</span>
      </div>
      <div className="ml-auto text-zinc-400">
        {formatDate(windowSince)} — {formatDate(windowUntil)}
      </div>
    </div>
  );
}
