import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { AiExplanation } from "./AiExplanation";

describe("AiExplanation", () => {
  it("renders narrative text", () => {
    render(
      <AiExplanation
        narrative="Detected lateral movement via pass-the-hash technique"
        provenance={["T1550.002", "T1021"]}
      />,
    );
    expect(
      screen.getByText("Detected lateral movement via pass-the-hash technique"),
    ).toBeInTheDocument();
  });

  it("renders provenance source tags", () => {
    render(
      <AiExplanation
        narrative="Some narrative"
        provenance={["T1550.002", "T1021", "TA0008"]}
      />,
    );
    expect(screen.getByText("T1550.002")).toBeInTheDocument();
    expect(screen.getByText("T1021")).toBeInTheDocument();
    expect(screen.getByText("TA0008")).toBeInTheDocument();
  });

  it("shows skeleton rows when loading=true", () => {
    render(
      <AiExplanation narrative="" provenance={[]} loading={true} />,
    );
    const skeletons = screen.getAllByTestId("ai-explanation-skeleton");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it("does not show skeleton when loading=false", () => {
    render(
      <AiExplanation narrative="Ready" provenance={[]} loading={false} />,
    );
    expect(screen.queryAllByTestId("ai-explanation-skeleton")).toHaveLength(0);
  });

  it("renders accessible section wrapper", () => {
    render(
      <AiExplanation
        narrative="Attack narrative here"
        provenance={["T1059"]}
      />,
    );
    expect(
      screen.getByRole("region", { name: /ai explanation/i }),
    ).toBeInTheDocument();
  });

  it("renders empty provenance gracefully", () => {
    render(
      <AiExplanation narrative="Narrative only" provenance={[]} />,
    );
    expect(screen.getByText("Narrative only")).toBeInTheDocument();
    expect(screen.queryByTestId("provenance-tag")).toBeNull();
  });

  it("renders each provenance tag as a chip", () => {
    render(
      <AiExplanation narrative="n" provenance={["T1001", "T1002", "T1003"]} />,
    );
    const tags = screen.getAllByTestId("provenance-tag");
    expect(tags).toHaveLength(3);
  });
});
