import { describe, it, expect, beforeEach, vi } from "vitest";

describe("useThemeStore", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    vi.resetModules();
  });

  it("defaults to 'light'", async () => {
    const { useThemeStore } = await import("./theme");
    expect(useThemeStore.getState().theme).toBe("light");
  });

  it("toggle() flips theme and writes to localStorage", async () => {
    const { useThemeStore } = await import("./theme");
    useThemeStore.getState().toggle();
    expect(useThemeStore.getState().theme).toBe("dark");
    expect(localStorage.getItem("seerflow.theme")).toBe("dark");
  });

  it("toggle() sets document.documentElement.dataset.theme", async () => {
    const { useThemeStore } = await import("./theme");
    useThemeStore.getState().toggle();
    expect(document.documentElement.dataset.theme).toBe("dark");
    useThemeStore.getState().toggle();
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("hydrates from localStorage on first access", async () => {
    localStorage.setItem("seerflow.theme", "dark");
    const { useThemeStore } = await import("./theme");
    expect(useThemeStore.getState().theme).toBe("dark");
  });
});
