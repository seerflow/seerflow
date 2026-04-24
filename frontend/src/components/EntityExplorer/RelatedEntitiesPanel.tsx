import type { EntityRelation } from "@/lib/types";

const LABELS: Record<string, string> = {
  authenticated_from: "Authenticated from",
  logged_into: "Logged into",
  has_ip: "Has IP",
  accessed: "Accessed",
  resolved_to: "Resolved to",
  spawned_by: "Spawned by",
};

function humanize(rt: string): string { return LABELS[rt] ?? rt; }

interface Props { related: EntityRelation[]; onNavigate: (uuid: string) => void; }

export function RelatedEntitiesPanel({ related, onNavigate }: Props) {
  if (related.length === 0) {
    return <div className="p-3 text-sm text-muted-foreground">No related entities for this entity.</div>;
  }
  const groups = related.reduce<Record<string, EntityRelation[]>>(
    (acc, r) => ({ ...acc, [r.relation_type]: [...(acc[r.relation_type] ?? []), r] }),
    {},
  );
  return (
    <aside aria-label="Related entities" className="flex flex-col gap-3">
      {Object.entries(groups).map(([rt, rows]) => (
        <section key={rt}>
          <header className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
            {humanize(rt)} <span className="ml-1 text-muted-foreground/70">({rows.length})</span>
          </header>
          <ul className="flex flex-col gap-0.5">
            {rows.map((r) => (
              <li key={r.entity_uuid}>
                <button
                  onClick={() => onNavigate(r.entity_uuid)}
                  className="flex w-full items-center gap-2 rounded px-2 py-1 text-sm hover:bg-accent"
                >
                  <span className="rounded border px-1.5 py-0.5 text-[10px] uppercase">{r.entity_type}</span>
                  <span className="flex-1 truncate text-left">{r.entity_value}</span>
                  <span className="text-xs text-muted-foreground">…{r.entity_uuid.slice(-8)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </aside>
  );
}
