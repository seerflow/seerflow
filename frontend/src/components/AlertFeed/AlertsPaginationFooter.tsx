import { PageBtn } from "./AlertConsoleParts";

export const ROWS_PER_PAGE_OPTIONS = [25, 50, 100] as const;
export type RowsPerPage = (typeof ROWS_PER_PAGE_OPTIONS)[number];

interface Props {
  total: number;
  page: number;
  rowsPerPage: number;
  onPageChange: (page: number) => void;
  onRowsPerPageChange: (rows: RowsPerPage) => void;
}

/**
 * Compute the (1-based) page-window button labels with leading/trailing ellipsis,
 * mirroring the mockup: ‹ 1 2 3 … last › with the active page highlighted.
 * Always includes page 1 and the last page; shows a small window around `page`.
 */
function pageWindow(page: number, pageCount: number): Array<number | "…"> {
  if (pageCount <= 5) return Array.from({ length: pageCount }, (_, i) => i + 1);
  const out: Array<number | "…"> = [1];
  const start = Math.max(2, page - 1);
  const end = Math.min(pageCount - 1, page + 1);
  if (start > 2) out.push("…");
  for (let p = start; p <= end; p++) out.push(p);
  if (end < pageCount - 1) out.push("…");
  out.push(pageCount);
  return out;
}

/**
 * Client-side pagination footer (S-336). The alert store has no server-side
 * paging, so this paginates the loaded/filtered set: "showing X–Y of N · page
 * n/m", rows-per-page (25/50/100), and page buttons.
 */
export function AlertsPaginationFooter({
  total,
  page,
  rowsPerPage,
  onPageChange,
  onRowsPerPageChange,
}: Props): JSX.Element {
  const pageCount = Math.max(1, Math.ceil(total / rowsPerPage));
  const clampedPage = Math.min(page, pageCount);
  const start = total === 0 ? 0 : (clampedPage - 1) * rowsPerPage + 1;
  const end = Math.min(total, clampedPage * rowsPerPage);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "10px 28px",
        borderTop: "1px solid var(--line)",
        background: "var(--surface)",
      }}
    >
      <span
        data-testid="alerts-page-summary"
        className="sf-mono"
        style={{ fontSize: 11, color: "var(--text-3)" }}
      >
        showing {start}–{end} of {total} · page {clampedPage} / {pageCount}
      </span>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span className="sf-mono" style={{ fontSize: 11, color: "var(--text-3)", marginRight: 6 }}>
          rows
        </span>
        {ROWS_PER_PAGE_OPTIONS.map((n) => {
          const isActive = n === rowsPerPage;
          return (
            <button
              key={n}
              type="button"
              aria-pressed={isActive}
              onClick={() => onRowsPerPageChange(n)}
              className="sf-mono"
              style={{
                fontSize: 11,
                padding: "3px 8px",
                color: isActive ? "var(--text)" : "var(--text-3)",
                border: "1px solid var(--line)",
                background: isActive ? "var(--surface-2)" : "transparent",
                cursor: "pointer",
              }}
            >
              {n}
            </button>
          );
        })}
        <span style={{ width: 1, height: 14, background: "var(--line)", margin: "0 4px" }} aria-hidden />
        <PageBtn disabled={clampedPage <= 1} onClick={() => onPageChange(clampedPage - 1)}>
          ‹
        </PageBtn>
        {pageWindow(clampedPage, pageCount).map((p, i) =>
          p === "…" ? (
            <span
              key={`gap-${i}`}
              className="sf-mono"
              style={{ fontSize: 11, color: "var(--text-3)" }}
              aria-hidden
            >
              …
            </span>
          ) : (
            <PageBtn key={p} active={p === clampedPage} onClick={() => onPageChange(p)}>
              {p}
            </PageBtn>
          ),
        )}
        <PageBtn disabled={clampedPage >= pageCount} onClick={() => onPageChange(clampedPage + 1)}>
          ›
        </PageBtn>
      </div>
    </div>
  );
}
