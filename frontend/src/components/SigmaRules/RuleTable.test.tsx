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

describe("RuleTable", () => {
  it("renders one row per rule", () => {
    render(
      <RuleTable
        rules={[sample("a", "AAA"), sample("b", "BBB")]}
        onSelect={() => {}}
        onToggle={() => {}}
      />,
    );
    expect(screen.getByText("AAA")).toBeInTheDocument();
    expect(screen.getByText("BBB")).toBeInTheDocument();
  });

  it("renders empty-state when no rules", () => {
    render(<RuleTable rules={[]} onSelect={() => {}} onToggle={() => {}} />);
    expect(screen.getByTestId("sigma-rules-empty")).toBeInTheDocument();
  });

  it("renders header columns", () => {
    render(<RuleTable rules={[sample("a", "A")]} onSelect={() => {}} onToggle={() => {}} />);
    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("Severity")).toBeInTheDocument();
    expect(screen.getByText(/24h alerts/i)).toBeInTheDocument();
  });
});
