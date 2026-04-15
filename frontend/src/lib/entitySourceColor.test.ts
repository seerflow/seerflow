import { describe, it, expect } from "vitest";
import { entitySourceColor } from "./entitySourceColor";

describe("entitySourceColor", () => {
  it("returns a stable HSL triple for the same key", () => {
    expect(entitySourceColor("syslog")).toBe(entitySourceColor("syslog"));
  });
  it("returns different colors for different keys", () => {
    expect(entitySourceColor("syslog")).not.toBe(entitySourceColor("k8s"));
  });
  it("returns hsl() string in expected format", () => {
    const value = entitySourceColor("zeek");
    expect(value).toMatch(/^hsl\(\d+(\.\d+)?,\s*65%,\s*\d+%\)$/);
  });
  it("distinguishes light vs dark lightness when theme passed", () => {
    expect(entitySourceColor("zeek", "light")).not.toBe(entitySourceColor("zeek", "dark"));
  });
});
