import type { AlertFilter, AlertType, SeverityBucket } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { SeverityChip } from "@/components/ui/SeverityChip";
import { cn } from "@/lib/utils";

const SEVS: SeverityBucket[] = ["critical", "high", "medium", "low"];
const TYPES: AlertType[] = ["ml", "sigma", "correlation", "ueba", "ioc"];

function toggle<T>(set: Set<T>, v: T): Set<T> {
  const next = new Set(set);
  if (next.has(v)) next.delete(v);
  else next.add(v);
  return next;
}

interface Props {
  filter: AlertFilter;
  sources: string[];
  tactics: string[];
  onChange: (p: Partial<AlertFilter>) => void;
}

export function FilterBar({ filter, sources, tactics, onChange }: Props): JSX.Element {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b p-2">
      {SEVS.map(s => (
        <SeverityChip key={s} label={s[0].toUpperCase() + s.slice(1)}
          active={filter.severities.has(s)}
          onToggle={() => onChange({ severities: toggle(filter.severities, s) })} />
      ))}
      <span className="mx-2 text-muted-foreground">·</span>
      {TYPES.map(t => (
        <Button key={t} size="sm" variant="outline" aria-pressed={filter.types.has(t)}
          className={cn(filter.types.has(t) && "bg-primary text-primary-foreground")}
          onClick={() => onChange({ types: toggle(filter.types, t) })}>
          {t}
        </Button>
      ))}
      {sources.length > 0 && <><span className="mx-2 text-muted-foreground">·</span>
        {sources.map(src => (
          <Button key={src} size="sm" variant="ghost" aria-pressed={filter.sources.has(src)}
            className={cn(filter.sources.has(src) && "bg-primary/20")}
            onClick={() => onChange({ sources: toggle(filter.sources, src) })}>{src}</Button>
        ))}</>}
      {tactics.length > 0 && <><span className="mx-2 text-muted-foreground">·</span>
        {tactics.map(t => (
          <Button key={t} size="sm" variant="ghost" aria-pressed={filter.tactics.has(t)}
            className={cn(filter.tactics.has(t) && "bg-primary/20")}
            onClick={() => onChange({ tactics: toggle(filter.tactics, t) })}>{t}</Button>
        ))}</>}
    </div>
  );
}
