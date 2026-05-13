import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const css = fs.readFileSync(
  path.resolve(__dirname, "./globals.css"),
  "utf8",
);

describe("globals.css theme tokens", () => {
  it("defines light-mode custom properties on :root", () => {
    expect(css).toMatch(/:root\s*{[^}]*--bg:\s*[^;]+;/s);
    expect(css).toMatch(/:root\s*{[^}]*--fg:\s*[^;]+;/s);
    expect(css).toMatch(/:root\s*{[^}]*--muted:\s*[^;]+;/s);
    expect(css).toMatch(/:root\s*{[^}]*--accent:\s*[^;]+;/s);
  });

  it("overrides tokens under [data-theme='dark']", () => {
    expect(css).toMatch(/\[data-theme=["']dark["']\]\s*{[^}]*--bg:/s);
    expect(css).toMatch(/\[data-theme=["']dark["']\]\s*{[^}]*--fg:/s);
  });
});
