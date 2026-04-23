import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { TechniqueCell } from "./TechniqueCell";

const baseProps = {
  tactic: "execution",
  technique: "T1053",
  name: "Scheduled Task/Job",
  ruleCount: 3,
  alertCount: 2,
  ruleNames: ["sigma_rule_a", "sigma_rule_b", "sigma_rule_c"],
  covered: true,
  detected: true,
};

describe("TechniqueCell", () => {
  it("renders as a button", () => {
    render(<TechniqueCell {...baseProps} />);
    const btn = screen.getByRole("button", { name: /T1053 Scheduled Task\/Job/ });
    expect(btn.tagName).toBe("BUTTON");
    expect(btn).toHaveAttribute("type", "button");
  });

  it("aria-label encodes status + counts", () => {
    render(<TechniqueCell {...baseProps} />);
    const btn = screen.getByRole("button");
    expect(btn).toHaveAttribute(
      "aria-label",
      "T1053 Scheduled Task/Job — Detected, 3 rules, 2 alerts",
    );
  });

  it("aria-label says Covered when not detected", () => {
    render(<TechniqueCell {...baseProps} detected={false} alertCount={0} />);
    expect(screen.getByRole("button")).toHaveAttribute(
      "aria-label",
      "T1053 Scheduled Task/Job — Covered, 3 rules, 0 alerts",
    );
  });

  it("aria-label says Gap when not covered and not detected", () => {
    render(
      <TechniqueCell
        {...baseProps}
        covered={false}
        detected={false}
        ruleCount={0}
        alertCount={0}
        ruleNames={[]}
      />,
    );
    expect(screen.getByRole("button")).toHaveAttribute(
      "aria-label",
      "T1053 Scheduled Task/Job — Gap, 0 rules, 0 alerts",
    );
  });

  it("uses cell-detected class when both flags true", () => {
    render(<TechniqueCell {...baseProps} />);
    expect(screen.getByRole("button").className).toMatch(/cell-detected/);
  });

  it("uses cell-covered class when only covered", () => {
    render(<TechniqueCell {...baseProps} detected={false} />);
    expect(screen.getByRole("button").className).toMatch(/cell-covered/);
  });

  it("uses cell-gap class when uncovered", () => {
    render(<TechniqueCell {...baseProps} covered={false} detected={false} />);
    expect(screen.getByRole("button").className).toMatch(/cell-gap/);
  });

  it("calls onOpen with (tactic, technique) on click", () => {
    const onOpen = vi.fn();
    render(<TechniqueCell {...baseProps} onOpen={onOpen} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onOpen).toHaveBeenCalledWith("execution", "T1053");
  });

  it("calls onOpen on Enter key via native button activation", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<TechniqueCell {...baseProps} onOpen={onOpen} />);
    const btn = screen.getByRole("button");
    btn.focus();
    await user.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("does not throw when onOpen is omitted", () => {
    render(<TechniqueCell {...baseProps} />);
    expect(() => fireEvent.click(screen.getByRole("button"))).not.toThrow();
  });

  it("preserves the hover tooltip listing rule names", () => {
    render(<TechniqueCell {...baseProps} />);
    fireEvent.mouseEnter(screen.getByRole("button"));
    expect(screen.getByText(/sigma_rule_a/)).toBeInTheDocument();
    expect(screen.getByText(/sigma_rule_b/)).toBeInTheDocument();
    expect(screen.getByText(/Alerts \(window\): 2/)).toBeInTheDocument();
  });

  it("hides the tooltip on click (sheet takes over)", () => {
    render(<TechniqueCell {...baseProps} />);
    const btn = screen.getByRole("button");
    fireEvent.mouseEnter(btn);
    expect(screen.getByText(/sigma_rule_a/)).toBeInTheDocument();
    fireEvent.click(btn);
    expect(screen.queryByText(/sigma_rule_a/)).not.toBeInTheDocument();
  });
});
