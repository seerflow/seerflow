/**
 * EventTableHeader — sticky six-column header for the event table (S-325).
 * Grid columns match EventRow: 110px 50px 60px 130px 110px 1fr
 */
export function EventTableHeader(): JSX.Element {
  return (
    <div
      className="sf-mono"
      style={{
        display: "grid",
        gridTemplateColumns: "110px 50px 60px 130px 110px 1fr",
        gap: "14px",
        padding: "7px 24px",
        borderBottom: "1px solid var(--line)",
        color: "var(--text-3)",
        fontSize: "9.5px",
        textTransform: "uppercase",
        letterSpacing: "0.1em",
        userSelect: "none",
        background: "var(--surface)",
        position: "sticky",
        top: 0,
        zIndex: 1,
      }}
    >
      <span>timestamp</span>
      <span>level</span>
      <span>source</span>
      <span>host</span>
      <span>logger</span>
      <span>message</span>
    </div>
  );
}
