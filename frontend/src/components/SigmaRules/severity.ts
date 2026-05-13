// S-151: Sigma severity → human label, mirrors backend SeverityLevel mapping.
export const SEVERITY_LABEL: Record<number, string> = {
  0: "?",
  1: "info",
  2: "low",
  3: "medium",
  4: "high",
  5: "critical",
};

export function severityLabel(value: number): string {
  return SEVERITY_LABEL[value] ?? String(value);
}
