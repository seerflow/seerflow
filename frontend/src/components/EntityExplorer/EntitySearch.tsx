import { useEffect, useRef, useState } from "react";
import { useEntityStore } from "@/stores/entity";
import { navigateToEntity } from "@/lib/hash";
import type { EntitySearchResult } from "@/lib/types";

const DEBOUNCE_MS = 250;

function groupByType(rows: EntitySearchResult[]): Map<string, EntitySearchResult[]> {
  const m = new Map<string, EntitySearchResult[]>();
  for (const r of rows) {
    const t = r.entity_type || "other";
    if (!m.has(t)) m.set(t, []);
    m.get(t)!.push(r);
  }
  return m;
}

export function EntitySearch() {
  const query = useEntityStore((s) => s.query);
  const setQuery = useEntityStore((s) => s.setQuery);
  const runSearch = useEntityStore((s) => s.runSearch);
  const results = useEntityStore((s) => s.searchResults);
  const recent = useEntityStore((s) => s.recent);
  const pushRecent = useEntityStore((s) => s.pushRecent);
  const error = useEntityStore((s) => s.error);

  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const suppressOpenRef = useRef(false);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!query.trim()) return;
    timerRef.current = setTimeout(() => void runSearch(), DEBOUNCE_MS);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [query, runSearch]);

  const showing: EntitySearchResult[] = query.trim() ? results : recent;
  const groups = groupByType(showing);

  function navigate(r: EntitySearchResult) {
    pushRecent(r);
    navigateToEntity(r.entity_uuid);
    setOpen(false);
  }

  function handleKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setOpen(false);
      if (inputRef.current && document.activeElement !== inputRef.current) {
        suppressOpenRef.current = true;
        inputRef.current.focus();
        suppressOpenRef.current = false;
      }
      return;
    }
    if (!open || showing.length === 0) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(c + 1, showing.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
    if (e.key === "Enter") { e.preventDefault(); navigate(showing[cursor]); }
  }

  return (
    <div className="relative w-80" onBlur={(e) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node)) setOpen(false);
    }}>
      <input
        ref={inputRef}
        role="combobox"
        aria-label="Search entities"
        aria-expanded={open}
        aria-controls="entity-search-listbox"
        aria-autocomplete="list"
        placeholder="Search entities…"
        value={query}
        onChange={(e) => { setQuery(e.target.value.slice(0, 256)); setOpen(true); setCursor(0); }}
        onFocus={() => { if (!suppressOpenRef.current) setOpen(true); }}
        onKeyDown={handleKey}
        className="w-full rounded-md border px-3 py-1.5 text-sm bg-background"
      />
      {open && (
        <div
          id="entity-search-listbox"
          role="listbox"
          className="absolute z-20 mt-1 w-full max-h-96 overflow-auto rounded-md border bg-popover shadow-md"
        >
          {error && <div className="p-2 text-xs text-destructive">{error}</div>}
          {!query.trim() && recent.length > 0 && (
            <div className="p-2 text-xs font-semibold uppercase text-muted-foreground">Recent</div>
          )}
          {groups.size === 0 && query.trim() && !error && (
            <div className="p-3 text-sm text-muted-foreground">No entities match &quot;{query}&quot;</div>
          )}
          {[...groups.entries()].map(([type, rows]) => (
            <div key={type}>
              <div className="sticky top-0 bg-popover px-2 py-1 text-xs font-semibold uppercase text-muted-foreground">
                {type}
              </div>
              {rows.map((r) => {
                const idx = showing.indexOf(r);
                const selected = idx === cursor;
                return (
                  <button
                    key={r.entity_uuid}
                    role="option"
                    aria-selected={selected}
                    onMouseEnter={() => setCursor(idx)}
                    onMouseDown={(e) => { e.preventDefault(); navigate(r); }}
                    className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm ${selected ? "bg-accent" : ""}`}
                  >
                    <span className="font-medium">{r.entity_value}</span>
                    <span className="ml-auto text-xs text-muted-foreground">…{r.entity_uuid.slice(-8)}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
