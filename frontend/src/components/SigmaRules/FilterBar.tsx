// S-151: Filter bar above the Sigma rules table.
//
// Search is debounced 250ms client-side; the change is propagated as a
// patch the page can merge into its filter state. Selecting a category
// or toggling enabled-only fires immediately.
import { useEffect, useRef, useState } from "react";

import type { SigmaRuleFilter } from "@/lib/types";

interface Props {
  initialSearch?: string;
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

const SEARCH_DEBOUNCE_MS = 250;

export function FilterBar({ initialSearch = "", onChange }: Props): JSX.Element {
  const [search, setSearch] = useState(initialSearch);
  const firstRender = useRef(true);

  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    const t = setTimeout(() => onChange({ search }), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [search, onChange]);

  return (
    <div className="flex flex-wrap items-center gap-3 border-b px-3 py-2">
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
