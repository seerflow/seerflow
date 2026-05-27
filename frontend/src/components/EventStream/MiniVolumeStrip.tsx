import { MiniVolume } from "@/viz/MiniVolume";

interface Props {
  timestamps: number[];
  values: number[];
  critCount: number;
  warnCount: number;
  className?: string;
}

/**
 * MiniVolumeStrip — 60s event volume chart with crit/warn count summary.
 * Rendered above the event table in the EventStream main column (S-325).
 */
export function MiniVolumeStrip({ timestamps, values, critCount, warnCount, className }: Props): JSX.Element {
  return (
    <div
      className={className}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        padding: "8px 24px 0",
        borderBottom: "1px solid var(--line)",
      }}
    >
      {/* Label row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          color: "var(--text-3)",
          textTransform: "uppercase",
          letterSpacing: "0.1em",
        }}
      >
        <span>volume · 60s window</span>
        <span style={{ display: "flex", gap: 12 }}>
          <span style={{ color: "var(--crit)" }}>{critCount} crit</span>
          <span style={{ color: "var(--warn)" }}>{warnCount} warn</span>
        </span>
      </div>

      {/* Chart */}
      <MiniVolume
        timestamps={timestamps}
        values={values}
        height={28}
      />
    </div>
  );
}
