import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { TacticColumn } from "./TacticColumn";

const techniques = [
  {
    id: "T1053",
    name: "Scheduled Task/Job",
    ruleCount: 1,
    alertCount: 0,
    ruleNames: ["a"],
    covered: true,
    detected: false,
  },
];

describe("TacticColumn", () => {
  it("renders the tactic name and one cell per technique", () => {
    render(
      <TacticColumn
        tacticId="TA0002"
        tacticShortname="execution"
        tacticName="Execution"
        techniques={techniques}
      />,
    );
    expect(screen.getByText("Execution")).toBeInTheDocument();
    expect(screen.getByRole("button")).toHaveAttribute(
      "aria-label",
      expect.stringContaining("T1053"),
    );
  });

  it("forwards onOpen with the tactic shortname", () => {
    const onOpen = vi.fn();
    render(
      <TacticColumn
        tacticId="TA0002"
        tacticShortname="execution"
        tacticName="Execution"
        techniques={techniques}
        onOpen={onOpen}
      />,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onOpen).toHaveBeenCalledWith("execution", "T1053");
  });

  it("renders the tactic ID in mono display (e.g. TA0002)", () => {
    render(
      <TacticColumn
        tacticId="TA0002"
        tacticShortname="execution"
        tacticName="Execution"
        techniques={techniques}
      />,
    );
    expect(screen.getByText("TA0002")).toBeInTheDocument();
  });

  it("renders technique count label", () => {
    render(
      <TacticColumn
        tacticId="TA0001"
        tacticShortname="reconnaissance"
        tacticName="Reconnaissance"
        techniques={techniques}
      />,
    );
    expect(screen.getByText(/1 technique/)).toBeInTheDocument();
  });

  it("renders correct technique count for multiple techniques", () => {
    const multiTechs = [
      { ...techniques[0] },
      { id: "T1595", name: "Active Scanning", ruleCount: 0, alertCount: 0, ruleNames: [], covered: false, detected: false },
      { id: "T1596", name: "Search OSINTs", ruleCount: 0, alertCount: 0, ruleNames: [], covered: false, detected: false },
    ];
    render(
      <TacticColumn
        tacticId="TA0043"
        tacticShortname="reconnaissance"
        tacticName="Reconnaissance"
        techniques={multiTechs}
      />,
    );
    expect(screen.getByText(/3 technique/)).toBeInTheDocument();
  });
});
