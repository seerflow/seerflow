import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { RuleTable } from "./RuleTable";
import type { SigmaRuleSummary } from "@/lib/types";

const sample = (id: string, title: string): SigmaRuleSummary => ({
  rule_id: id,
  title,
  description: "",
  severity: 3,
  logsource_key: ["", "linux", ""],
  attack_tactics: [],
  attack_techniques: [],
  enabled: true,
  source: "bundled",
  match_count_lifetime: 0,
  last_fired_ns: null,
  alert_count_24h: 0,
});

describe("RuleTable (S-341 mockup grid)", () => {
  it("renders one row per rule (by rule_id)", () => {
    render(
      <RuleTable
        rules={[sample("a", "AAA"), sample("b", "BBB")]}
        onSelect={() => {}}
        onToggle={() => {}}
      />,
    );
    // Mockup row shows rule_id (mono) as the primary cell — title was the
    // old `<table>` chrome.
    expect(screen.getByTestId("sigma-rule-row-a")).toBeInTheDocument();
    expect(screen.getByTestId("sigma-rule-row-b")).toBeInTheDocument();
  });

  it("renders empty-state when no rules", () => {
    render(<RuleTable rules={[]} onSelect={() => {}} onToggle={() => {}} />);
    expect(screen.getByTestId("sigma-rules-empty")).toBeInTheDocument();
  });

  it("renders mockup header cells: rule · tactic / hits 24h / prec", () => {
    render(
      <RuleTable rules={[sample("a", "A")]} onSelect={() => {}} onToggle={() => {}} />,
    );
    expect(screen.getByText("rule · tactic")).toBeInTheDocument();
    expect(screen.getByText("hits 24h")).toBeInTheDocument();
    expect(screen.getByText("prec")).toBeInTheDocument();
  });

  it("uses the mockup's 5-col grid template on the header", () => {
    render(
      <RuleTable rules={[sample("a", "A")]} onSelect={() => {}} onToggle={() => {}} />,
    );
    const header = screen.getByTestId("sigma-rules-table-header");
    expect(header).toHaveStyle({
      gridTemplateColumns: "12px 1fr 80px 60px 40px",
    });
  });

  it("marks the selected row with data-selected='true'", () => {
    render(
      <RuleTable
        rules={[sample("a", "A"), sample("b", "B")]}
        onSelect={() => {}}
        onToggle={() => {}}
        selectedRuleId="b"
      />,
    );
    expect(screen.getByTestId("sigma-rule-row-a")).toHaveAttribute(
      "data-selected",
      "false",
    );
    expect(screen.getByTestId("sigma-rule-row-b")).toHaveAttribute(
      "data-selected",
      "true",
    );
  });

  it("leaves all rows unselected when selectedRuleId is null/undefined", () => {
    render(
      <RuleTable
        rules={[sample("a", "A")]}
        onSelect={() => {}}
        onToggle={() => {}}
      />,
    );
    expect(screen.getByTestId("sigma-rule-row-a")).toHaveAttribute(
      "data-selected",
      "false",
    );
  });
});
