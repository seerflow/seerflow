import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AlertRow } from "./AlertRow";
import type { Alert } from "@/lib/types";

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
});
