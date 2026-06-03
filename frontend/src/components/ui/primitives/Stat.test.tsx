import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Stat } from "./Stat";

describe("Stat", () => {
  it("renders the label", () => {
    const { container } = render(<Stat label="events / sec" value="12,847" />);
    expect(container.textContent).toContain("events / sec");
  });

  it("renders the value", () => {
    const { container } = render(<Stat label="events / sec" value="12,847" />);
    expect(container.textContent).toContain("12,847");
  });

  it("renders optional delta", () => {
    const { container } = render(<Stat label="x" value="1" delta="+4.2%" />);
    expect(container.textContent).toContain("+4.2%");
  });

  it("value has sf-tnum class for tabular numbers", () => {
    const { container } = render(<Stat label="x" value="42" />);
    // The value element should have sf-tnum somewhere in its classes
    const el = container.querySelector("[class*='tnum'], .sf-tnum");
    expect(el).toBeTruthy();
  });

  it("label has sf-mono class", () => {
    const { container } = render(<Stat label="metric" value="1" />);
    const el = container.querySelector(".sf-mono");
    expect(el).toBeTruthy();
  });

  it("renders children as sparkline slot", () => {
    const { container } = render(
      <Stat label="x" value="1">
        <div id="sparkline" />
      </Stat>
    );
    expect(container.querySelector("#sparkline")).toBeTruthy();
  });
});
