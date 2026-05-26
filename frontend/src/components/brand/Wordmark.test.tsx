import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Wordmark } from "./Wordmark";

describe("Wordmark", () => {
  it("renders seerflow text", () => {
    const { container } = render(<Wordmark />);
    expect(container.textContent).toContain("seerflow");
  });

  it("renders the SeerMark image by default", () => {
    const { container } = render(<Wordmark />);
    expect(container.querySelector("img")).toBeTruthy();
  });

  it("hides the mark when mark={false}", () => {
    const { container } = render(<Wordmark mark={false} />);
    expect(container.querySelector("img")).toBeNull();
  });

  it("uses mono font family class", () => {
    const { container } = render(<Wordmark />);
    const textEl = container.querySelector("[class*='font-mono'], [class*='sf-mono']");
    expect(textEl).toBeTruthy();
  });
});
