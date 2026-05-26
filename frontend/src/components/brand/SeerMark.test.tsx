import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { SeerMark } from "./SeerMark";

describe("SeerMark", () => {
  it("renders an img element", () => {
    const { container } = render(<SeerMark />);
    expect(container.querySelector("img")).toBeTruthy();
  });

  it("defaults to color variant (seerflow_logo_color)", () => {
    render(<SeerMark />);
    const img = document.querySelector("img");
    expect(img?.getAttribute("src")).toContain("seerflow_logo_color");
  });

  it("dark variant uses seerflow_logo_dark", () => {
    render(<SeerMark variant="dark" />);
    const img = document.querySelector("img");
    expect(img?.getAttribute("src")).toContain("seerflow_logo_dark");
  });

  it("mono-white variant uses seerflow_logo_mono_white", () => {
    render(<SeerMark variant="mono-white" />);
    const img = document.querySelector("img");
    expect(img?.getAttribute("src")).toContain("seerflow_logo_mono_white");
  });

  it("mono-black variant uses seerflow_logo_mono_black", () => {
    render(<SeerMark variant="mono-black" />);
    const img = document.querySelector("img");
    expect(img?.getAttribute("src")).toContain("seerflow_logo_mono_black");
  });

  it("applies the given height via size prop", () => {
    render(<SeerMark size={32} />);
    const img = document.querySelector("img");
    expect(img?.getAttribute("height")).toBe("32");
  });

  it("is decorative (aria-hidden, empty alt)", () => {
    render(<SeerMark />);
    const img = document.querySelector("img");
    expect(img?.getAttribute("alt")).toBe("");
    expect(img?.getAttribute("aria-hidden")).toBe("true");
  });
});
