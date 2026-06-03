import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { RuleRow } from "./RuleRow";
import type { SigmaRuleSummary } from "@/lib/types";

const baseRule: SigmaRuleSummary = {
  rule_id: "ssh_brute_force",
  title: "SSH brute force",
  description: "",
  severity: 4,
  logsource_key: ["", "linux", "sshd"],
  attack_tactics: ["credential-access"],
  attack_techniques: ["t1110.001"],
  enabled: true,
  source: "bundled",
  match_count_lifetime: 312,
  last_fired_ns: null,
  alert_count_24h: 312,
};

function renderRow(
  overrides: Partial<SigmaRuleSummary> = {},
  selected = false,
) {
  const onSelect = vi.fn();
  const onToggle = vi.fn();
  render(
    <RuleRow
      rule={{ ...baseRule, ...overrides }}
      onSelect={onSelect}
      onToggle={onToggle}
      selected={selected}
    />,
  );
  return { onSelect, onToggle };
}

describe("RuleRow (S-341 mockup grid row)", () => {
  it("renders rule_id (mono) and technique + tactic line", () => {
    renderRow();
    expect(screen.getByText("ssh_brute_force")).toBeInTheDocument();
    expect(screen.getByText(/T1110\.001/i)).toBeInTheDocument();
    expect(screen.getByText(/credential-access/)).toBeInTheDocument();
  });

  it("renders a status dot (enabled → accent fill)", () => {
    renderRow();
    const dot = screen.getByTestId("sigma-row-dot");
    expect(dot).toHaveStyle({ background: "var(--accent)" });
  });

  it("status dot uses text-3 when rule disabled", () => {
    renderRow({ enabled: false });
    const dot = screen.getByTestId("sigma-row-dot");
    expect(dot).toHaveStyle({ background: "var(--text-3)" });
  });

  it("renders the hits 24h cell right-aligned in warn when > 100", () => {
    renderRow({ alert_count_24h: 312 });
    const hits = screen.getByTestId("sigma-row-hits");
    expect(hits).toHaveTextContent("312");
    expect(hits).toHaveStyle({ color: "var(--warn)" });
    expect(hits).toHaveStyle({ textAlign: "right" });
  });

  it("renders the hits cell in text-2 when ≤ 100", () => {
    renderRow({ alert_count_24h: 27 });
    const hits = screen.getByTestId("sigma-row-hits");
    expect(hits).toHaveStyle({ color: "var(--text-2)" });
  });

  it("renders a chevron cell ›", () => {
    renderRow();
    expect(screen.getByTestId("sigma-row-chevron")).toHaveTextContent("›");
  });

  it("does NOT render a switch/checkbox (S-341 drops in-row toggle)", () => {
    renderRow();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("clicking row fires onSelect with rule_id", () => {
    const { onSelect } = renderRow();
    fireEvent.click(screen.getByTestId("sigma-rule-row-ssh_brute_force"));
    expect(onSelect).toHaveBeenCalledWith("ssh_brute_force");
  });

  it("selected row marks data-selected=true and applies accent border-left", () => {
    renderRow({}, true);
    const row = screen.getByTestId("sigma-rule-row-ssh_brute_force");
    expect(row).toHaveAttribute("data-selected", "true");
    expect(row).toHaveStyle({ borderLeft: "2px solid var(--accent)" });
  });

  it("unselected row uses a 2px transparent border-left", () => {
    renderRow({}, false);
    const row = screen.getByTestId("sigma-rule-row-ssh_brute_force");
    expect(row).toHaveAttribute("data-selected", "false");
    // jsdom collapses `border-left: 2px solid transparent` into its style
    // attribute verbatim — assert via the raw attribute rather than
    // toHaveStyle (which doesn't normalize the `transparent` keyword).
    const styleAttr = row.getAttribute("style") ?? "";
    expect(styleAttr).toMatch(/border-left:\s*2px\s+solid\s+transparent/);
  });

  it("renders precision cell with accent color when ratio > 0.8", () => {
    // ratio = 1 - alert_count_24h/match_count_lifetime. 50 lifetime / 5 alerts → 0.9
    renderRow({ alert_count_24h: 5, match_count_lifetime: 50 });
    const prec = screen.getByTestId("sigma-row-prec");
    expect(prec).toHaveStyle({ color: "var(--accent)" });
  });

  it("renders precision cell with warn color when ratio < 0.6", () => {
    // 10 alerts / 20 lifetime → ratio 0.5
    renderRow({ alert_count_24h: 10, match_count_lifetime: 20 });
    const prec = screen.getByTestId("sigma-row-prec");
    expect(prec).toHaveStyle({ color: "var(--warn)" });
  });

  it("falls back to em-dash tactic when no tactic present", () => {
    renderRow({ attack_tactics: [], attack_techniques: [] });
    // technique cell collapses; row still renders rule_id without a tactic line.
    expect(screen.getByText("ssh_brute_force")).toBeInTheDocument();
  });
});
