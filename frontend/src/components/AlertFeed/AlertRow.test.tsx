import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AlertRow } from "./AlertRow";
import type { Alert } from "@/lib/types";

function mkAlert(over: Partial<Alert> = {}): Alert {
  return {
    alert_id: "kc-94-1afe2b",
    timestamp_ns: BigInt(Date.now()) * 1_000_000n - 12n * 1_000_000_000n,
    alert_type: "correlation",
    rule_name: "kill_chain · credential-access → lateral-movement",
    severity: 6,
    risk_score: 0.94,
    entity_uuid: null,
    entity_type: "user",
    entity_value: "root@10.0.1.42",
    message: "4 tactics correlated within 12m",
    mitre_tactics: ["TA0006", "TA0008", "TA0004", "TA0007"],
    mitre_techniques: [],
    dedup_count: 47,
    source_type: "syslog",
    feedback: "",
    ...over,
  };
}

describe("AlertRow", () => {
  it("renders rule name, alert id, score and event count", () => {
    render(<AlertRow alert={mkAlert()} selected={false} onOpen={() => {}} />);
    expect(screen.getByText(/kill_chain · credential-access/)).toBeInTheDocument();
    expect(screen.getByText("kc-94-1afe2b")).toBeInTheDocument();
    expect(screen.getByText("0.94")).toBeInTheDocument();
    expect(screen.getByText("47")).toBeInTheDocument();
  });

  it("exposes the alert as a button labelled by rule name", () => {
    render(<AlertRow alert={mkAlert()} selected={false} onOpen={() => {}} />);
    expect(
      screen.getByRole("button", { name: /alert kill_chain · credential-access/ }),
    ).toBeInTheDocument();
  });

  it("shows the N× tactic badge when more than one tactic", () => {
    render(<AlertRow alert={mkAlert()} selected={false} onOpen={() => {}} />);
    expect(screen.getByText("4× tactic")).toBeInTheDocument();
  });

  it("omits the tactic badge for a single tactic", () => {
    render(<AlertRow alert={mkAlert({ mitre_tactics: ["TA0006"] })} selected={false} onOpen={() => {}} />);
    expect(screen.queryByText(/× tactic/)).not.toBeInTheDocument();
  });

  it("renders the entity chip from the live entity ref", () => {
    render(<AlertRow alert={mkAlert()} selected={false} onOpen={() => {}} />);
    expect(screen.getByText("root@10.0.1.42")).toBeInTheDocument();
  });

  it("fires onOpen with the alert id on click", () => {
    const onOpen = vi.fn();
    render(<AlertRow alert={mkAlert()} selected={false} onOpen={onOpen} />);
    fireEvent.click(screen.getByRole("button", { name: /alert kill_chain/ }));
    expect(onOpen).toHaveBeenCalledWith("kc-94-1afe2b");
  });

  it("fires onOpen on Enter key", () => {
    const onOpen = vi.fn();
    render(<AlertRow alert={mkAlert()} selected={false} onOpen={onOpen} />);
    fireEvent.keyDown(screen.getByRole("button", { name: /alert kill_chain/ }), { key: "Enter" });
    expect(onOpen).toHaveBeenCalledWith("kc-94-1afe2b");
  });

  it("no longer renders feedback (TP/FP) controls", () => {
    render(<AlertRow alert={mkAlert()} selected={false} onOpen={() => {}} />);
    expect(screen.queryByRole("button", { name: /true positive/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /false positive/i })).not.toBeInTheDocument();
  });

  it("renders the owner cell (demo avatar or unassigned dash)", () => {
    render(<AlertRow alert={mkAlert()} selected={false} onOpen={() => {}} />);
    expect(screen.getByTestId("alert-owner")).toBeInTheDocument();
  });
});
