import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AlertRow } from "./AlertRow";
import type { Alert } from "@/lib/types";

vi.mock("@/lib/feedback", () => ({ submitFeedback: vi.fn() }));

const alert: Alert = {
  alert_id: "a1", timestamp_ns: 1_700_000_000_000_000_000n, alert_type: "sigma",
  rule_name: "SSH brute force", severity: 17, risk_score: 0.92,
  entity_uuid: null, entity_type: "ip", entity_value: "10.0.0.1",
  message: "matched", mitre_tactics: ["TA0006"], mitre_techniques: ["T1110"],
  dedup_count: 3, source_type: "syslog",
};

describe("AlertRow", () => {
  it("renders severity label + rule name + entity value", () => {
    render(<AlertRow alert={alert} onClick={() => {}} />);
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("SSH brute force")).toBeInTheDocument();
    expect(screen.getByText("10.0.0.1")).toBeInTheDocument();
  });

  it("fires onClick with alert_id", () => {
    const onClick = vi.fn();
    render(<AlertRow alert={alert} onClick={onClick} />);
    fireEvent.click(screen.getByRole("button", { name: /alert/i }));
    expect(onClick).toHaveBeenCalledWith("a1");
  });

  it("renders boundary timestamp_ns above 2^53 without precision loss (S-194 AC-1)", () => {
    const a: Alert = { ...alert, timestamp_ns: 1_700_000_000_000_000_123n };
    render(<AlertRow alert={a} onClick={() => {}} />);
    expect(screen.getByText("22:13:20")).toBeInTheDocument();
  });

  it("renders ✓ and ✗ buttons with aria labels (S-066)", () => {
    render(<AlertRow alert={alert} onClick={vi.fn()} />);
    expect(screen.getByRole("button", { name: /mark true positive/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /mark false positive/i })).toBeInTheDocument();
  });

  it("clicking TP button does not toggle expand (S-066)", async () => {
    const onClick = vi.fn();
    const { submitFeedback } = await import("@/lib/feedback");
    render(<AlertRow alert={alert} onClick={onClick} />);
    fireEvent.click(screen.getByRole("button", { name: /mark true positive/i }));
    expect(onClick).not.toHaveBeenCalled();
    expect(submitFeedback).toHaveBeenCalledWith("a1", "tp");
  });

  it("Enter keydown on TP button does not toggle expand (S-066)", () => {
    const onClick = vi.fn();
    render(<AlertRow alert={alert} onClick={onClick} />);
    const tpButton = screen.getByRole("button", { name: /mark true positive/i });
    tpButton.focus();
    fireEvent.keyDown(tpButton, { key: "Enter" });
    expect(onClick).not.toHaveBeenCalled();
  });
});
