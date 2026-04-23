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
        tacticShortname="execution"
        tacticName="Execution"
        techniques={techniques}
        onOpen={onOpen}
      />,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onOpen).toHaveBeenCalledWith("execution", "T1053");
  });
});
