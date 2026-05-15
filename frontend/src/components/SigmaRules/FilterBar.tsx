// S-151: Filter bar above the Sigma rules table.
//
// Search is debounced 250ms client-side; the change is propagated as a
// patch the page can merge into its filter state. Selecting a category /
// product / severity or toggling enabled-only fires immediately.
//
// S-154 (T8): the single severity `<select>` is replaced by a multi-select
// emitting `severity_in: number[]`. An empty selection means "no filter" —
// `buildQuery` in sigmaRulesApi already strips empty arrays so no
// `?severity_in=` token reaches the backend.
//
// S-230 / SEE-241: the severity multi-select renders as a Button +
// aria-pressed chip group (matching AlertFeed/FilterBar) instead of raw
// checkboxes, and the container padding aligns to the canonical
// `border-b p-2`.
import { useEffect, useRef, useState } from "react";

import type { SigmaRuleFilter } from "@/lib/types";
import { SeverityChip } from "@/components/ui/SeverityChip";

interface Props {
  initialSearch?: string;
  initialSeverityIn?: number[];
  onChange: (patch: Partial<SigmaRuleFilter>) => void;
}

const CATEGORIES: ReadonlyArray<{ value: string; label: string }> = [
  { value: "", label: "All categories" },
  { value: "linux", label: "linux" },
  { value: "web", label: "web" },
  { value: "dns", label: "dns" },
  { value: "process_creation", label: "process_creation" },
  { value: "network", label: "network" },
  { value: "authentication", label: "authentication" },
];

const PRODUCTS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "", label: "All products" },
  { value: "linux", label: "linux" },
  { value: "windows", label: "windows" },
  { value: "macos", label: "macos" },
  { value: "apache", label: "apache" },
  { value: "nginx", label: "nginx" },
];

// Backend `severity` matches the OCSF SeverityLevel enum used by Alert:
// 1=info, 2=low, 3=medium, 4=high, 5=critical. Order in the UI is
// high-severity-first to mirror the sort operators expect when triaging.
const SEVERITIES: ReadonlyArray<{ value: number; label: string }> = [
  { value: 5, label: "critical" },
  { value: 4, label: "high" },
  { value: 3, label: "medium" },
  { value: 2, label: "low" },
  { value: 1, label: "info" },
];

const SEARCH_DEBOUNCE_MS = 250;

export function FilterBar({
  initialSearch = "",
  initialSeverityIn = [],
  onChange,
}: Props): JSX.Element {
  const [search, setSearch] = useState(initialSearch);
  const [severityIn, setSeverityIn] = useState<number[]>(initialSeverityIn);
  const firstRender = useRef(true);

  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    const t = setTimeout(() => onChange({ search }), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [search, onChange]);

  function toggleSeverity(value: number, checked: boolean): void {
    // Immutable update — preserves checkbox click order, which the test
    // harness asserts on (most-recently-checked appears last).
    const next = checked
      ? [...severityIn.filter((s) => s !== value), value]
      : severityIn.filter((s) => s !== value);
    setSeverityIn(next);
    onChange({ severity_in: next });
  }

  return (
    <div className="flex flex-wrap items-center gap-3 border-b p-2">
      <input
        type="search"
        placeholder="Search rules…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="h-9 w-64 rounded-md border bg-background px-2 text-sm"
        aria-label="Search Sigma rules"
      />
      <select
        className="h-9 rounded-md border bg-background px-2 text-sm"
        onChange={(e) => onChange({ category: e.target.value || null })}
        aria-label="Filter by category"
        defaultValue=""
      >
        {CATEGORIES.map((c) => (
          <option key={c.value} value={c.value}>
            {c.label}
          </option>
        ))}
      </select>
      <select
        className="h-9 rounded-md border bg-background px-2 text-sm"
        onChange={(e) => onChange({ logsource_product: e.target.value || null })}
        aria-label="Filter by logsource product"
        defaultValue=""
      >
        {PRODUCTS.map((p) => (
          <option key={p.value} value={p.value}>
            {p.label}
          </option>
        ))}
      </select>
      <span className="sr-only" id="sigma-severity-label">
        Filter by severity
      </span>
      <div
        className="flex flex-wrap items-center gap-2"
        role="group"
        aria-labelledby="sigma-severity-label"
      >
        {SEVERITIES.map((s) => {
          const active = severityIn.includes(s.value);
          return (
            <SeverityChip
              key={s.value}
              label={s.label}
              active={active}
              onToggle={() => toggleSeverity(s.value, !active)}
            />
          );
        })}
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          onChange={(e) => onChange({ enabledOnly: e.target.checked })}
          className="h-4 w-4 cursor-pointer accent-primary"
        />
        Enabled only
      </label>
    </div>
  );
}
