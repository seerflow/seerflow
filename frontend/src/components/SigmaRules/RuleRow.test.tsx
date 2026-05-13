import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { RuleRow } from "./RuleRow";
import type { SigmaRuleSummary } from "@/lib/types";

const baseRule: SigmaRuleSummary = {
  rule_id: "r1",
  title: "Test Rule",
  description: "",
  severity: 4,
  logsource_key: ["", "linux", ""],
  attack_tactics: ["execution"],
  attack_techniques: ["t1059", "t1059.001"],
  enabled: true,
  source: "bundled",
  match_count_lifetime: 5,
  last_fired_ns: null,
  alert_count_24h: 2,
};

function renderRow(overrides: Partial<SigmaRuleSummary> = {}, handlers = {}) {
  const onSelect = vi.fn();
  const onToggle = vi.fn();
  render(
    <table>
      <tbody>
        <RuleRow rule={{ ...baseRule, ...overrides }} onSelect={onSelect} onToggle={onToggle} {...handlers} />
      </tbody>
    </table>,
  );
  return { onSelect, onToggle };
}

describe("RuleRow", () => {
  it("renders title, severity, logsource, counts", () => {
    renderRow();
    expect(screen.getByText("Test Rule")).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByText("linux")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("clicking row fires onSelect with rule id", () => {
    const { onSelect } = renderRow();
    fireEvent.click(screen.getByText("Test Rule"));
    expect(onSelect).toHaveBeenCalledWith("r1");
  });

  it("clicking switch fires onToggle with inverse and stops propagation", () => {
    const { onSelect, onToggle } = renderRow();
    fireEvent.click(screen.getByRole("switch"));
    expect(onToggle).toHaveBeenCalledWith("r1", false);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("truncates >3 attack techniques with ellipsis", () => {
    renderRow({ attack_techniques: ["t1", "t2", "t3", "t4"] });
    expect(screen.getByText(/t1, t2, t3…/)).toBeInTheDocument();
  });

  it("renders em dash when no logsource and no techniques", () => {
    renderRow({
      logsource_key: ["", "", ""],
      attack_techniques: [],
    });
    expect(screen.getAllByText("—").length).toBe(2);
  });
});
