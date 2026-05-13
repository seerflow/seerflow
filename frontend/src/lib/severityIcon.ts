export type SeverityTone = "neutral" | "info" | "warn" | "error" | "crit";

export interface SeverityIcon {
  label: string;
  emoji: string;
  tone: SeverityTone;
}

const TABLE: SeverityIcon[] = [
  { label: "TRACE",  emoji: "·", tone: "neutral" },
  { label: "DEBUG",  emoji: "🐛", tone: "neutral" },
  { label: "INFO",   emoji: "ℹ", tone: "info" },
  { label: "NOTICE", emoji: "📌", tone: "info" },
  { label: "WARN",   emoji: "⚠", tone: "warn" },
  { label: "ERROR",  emoji: "✖", tone: "error" },
  { label: "FATAL",  emoji: "🛑", tone: "crit" },
];

export function severityIcon(id: number): SeverityIcon {
  const clamped = Math.max(0, Math.min(TABLE.length - 1, Math.trunc(id)));
  return TABLE[clamped];
}
