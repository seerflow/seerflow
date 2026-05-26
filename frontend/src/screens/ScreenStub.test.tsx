import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ScreenStub } from "./ScreenStub";

describe("ScreenStub", () => {
  it("renders the provided label", () => {
    render(<ScreenStub label="Alerts" />);
    expect(screen.getByText("Alerts")).toBeInTheDocument();
  });

  it("renders COMING SOON text", () => {
    render(<ScreenStub label="Hunt" />);
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
  });

  it("renders brand mark (aria-hidden img)", () => {
    const { container } = render(<ScreenStub label="Models" />);
    const img = container.querySelector('img[aria-hidden="true"]');
    expect(img).not.toBeNull();
  });

  it("renders 'under construction' message", () => {
    render(<ScreenStub label="Settings" />);
    expect(screen.getByText(/under construction/i)).toBeInTheDocument();
  });
});
