import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TechniqueCell } from "./TechniqueCell";

describe("TechniqueCell", () => {
  const base = { tactic: "persistence", technique: "T1053", name: "Scheduled Task/Job" };

  it("renders with detected color when covered and detected", () => {
    const { container } = render(
      <TechniqueCell {...base} ruleCount={2} alertCount={3} ruleNames={["r1", "r2"]} covered detected />,
    );
    expect(container.firstElementChild).toHaveClass("cell-detected");
  });

  it("renders with covered color when covered but not detected", () => {
    const { container } = render(
      <TechniqueCell {...base} ruleCount={1} alertCount={0} ruleNames={["r1"]} covered detected={false} />,
    );
    expect(container.firstElementChild).toHaveClass("cell-covered");
  });

  it("renders with gap color when not covered", () => {
    const { container } = render(
      <TechniqueCell {...base} ruleCount={0} alertCount={0} ruleNames={[]} covered={false} detected={false} />,
    );
    expect(container.firstElementChild).toHaveClass("cell-gap");
  });

  it("shows tooltip with rule names on hover", async () => {
    render(
      <TechniqueCell {...base} ruleCount={2} alertCount={1} ruleNames={["sched_task", "crontab"]} covered detected />,
    );
    const cell = screen.getByTitle("T1053 — Scheduled Task/Job");
    await userEvent.hover(cell);
    expect(screen.getByText("sched_task")).toBeInTheDocument();
    expect(screen.getByText("crontab")).toBeInTheDocument();
  });

  it("shows no-coverage message in tooltip for gap cells", async () => {
    render(
      <TechniqueCell {...base} ruleCount={0} alertCount={0} ruleNames={[]} covered={false} detected={false} />,
    );
    const cell = screen.getByTitle("T1053 — Scheduled Task/Job");
    await userEvent.hover(cell);
    expect(screen.getByText(/no rules loaded/i)).toBeInTheDocument();
  });
});
