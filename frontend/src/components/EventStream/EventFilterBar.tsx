import { useState } from "react";
import type { EventFilter } from "@/lib/types";

interface Props {
  filter: EventFilter;
  knownSources: string[];
  onChange: (next: Partial<EventFilter>) => void;
}

const MAX_TEMPLATE_CHIPS = 100;

export function EventFilterBar({ filter, knownSources, onChange }: Props): JSX.Element {
  const [tplDraft, setTplDraft] = useState("");

  const toggleSource = (s: string): void => {
    const next = new Set(filter.sources);
    if (next.has(s)) next.delete(s); else next.add(s);
    onChange({ sources: next });
  };

  const addTemplate = (): void => {
    const n = Number.parseInt(tplDraft, 10);
    if (!Number.isInteger(n) || n < 0) return;
    if (filter.templateIds.size >= MAX_TEMPLATE_CHIPS) return;
    const next = new Set(filter.templateIds);
    next.add(n);
    onChange({ templateIds: next });
    setTplDraft("");
  };

  const removeTemplate = (n: number): void => {
    const next = new Set(filter.templateIds);
    next.delete(n);
    onChange({ templateIds: next });
  };

  return (
    <div className="flex flex-wrap items-center gap-2 border-b px-2 py-1.5 text-xs">
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-muted-foreground">sources:</span>
        {knownSources.length === 0 && <span className="text-muted-foreground">—</span>}
        {knownSources.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => toggleSource(s)}
            aria-pressed={filter.sources.has(s)}
            className={`rounded px-1.5 py-0.5 ${filter.sources.has(s) ? "bg-primary text-primary-foreground" : "bg-secondary"}`}
          >
            {s}
          </button>
        ))}
      </div>
      <label className="flex items-center gap-1">
        <span className="text-muted-foreground">min severity</span>
        <select
          aria-label="min severity"
          value={filter.minSeverity}
          onChange={(e) => onChange({ minSeverity: Number.parseInt(e.target.value, 10) })}
          className="rounded border bg-background px-1 py-0.5"
        >
          <option value="0">TRACE</option>
          <option value="1">DEBUG</option>
          <option value="2">INFO</option>
          <option value="3">NOTICE</option>
          <option value="4">WARN</option>
          <option value="5">ERROR</option>
          <option value="6">FATAL</option>
        </select>
      </label>
      <div className="flex items-center gap-1">
        <span className="text-muted-foreground">template ids:</span>
        {[...filter.templateIds].map((n) => (
          <button key={n} type="button" onClick={() => removeTemplate(n)} className="rounded bg-secondary px-1.5 py-0.5">
            {n} ✕
          </button>
        ))}
        <input
          aria-label="template id"
          value={tplDraft}
          onChange={(e) => setTplDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTemplate(); } }}
          placeholder="add #"
          className="w-16 rounded border bg-background px-1 py-0.5"
        />
      </div>
    </div>
  );
}
