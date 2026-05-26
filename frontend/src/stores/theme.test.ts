import { describe, it, expect, beforeEach, vi } from "vitest";

describe("useThemeStore — .sf-light mechanism", () => {
  beforeEach(() => {
    localStorage.clear();
    // Clean up both old (data-theme) and new (.sf-light) mechanisms
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.classList.remove("sf-light");
    vi.resetModules();
  });

  it("defaults to 'dark' when no stored preference", async () => {
    const { useThemeStore } = await import("./theme");
    expect(useThemeStore.getState().theme).toBe("dark");
  });

  it("html has no sf-light class when theme is dark (default)", async () => {
    await import("./theme");
    expect(document.documentElement.classList.contains("sf-light")).toBe(false);
  });

  it("toggle() flips dark→light and adds sf-light class to <html>", async () => {
    const { useThemeStore } = await import("./theme");
    expect(useThemeStore.getState().theme).toBe("dark");
    useThemeStore.getState().toggle();
    expect(useThemeStore.getState().theme).toBe("light");
    expect(document.documentElement.classList.contains("sf-light")).toBe(true);
  });

  it("toggle() flips light→dark and removes sf-light class from <html>", async () => {
    const { useThemeStore } = await import("./theme");
    useThemeStore.getState().toggle(); // dark → light
    useThemeStore.getState().toggle(); // light → dark
    expect(useThemeStore.getState().theme).toBe("dark");
    expect(document.documentElement.classList.contains("sf-light")).toBe(false);
  });

  it("persists to localStorage with key 'seerflow-theme'", async () => {
    const { useThemeStore } = await import("./theme");
    useThemeStore.getState().toggle();
    expect(localStorage.getItem("seerflow-theme")).toBe("light");
    useThemeStore.getState().toggle();
    expect(localStorage.getItem("seerflow-theme")).toBe("dark");
  });

  it("does NOT write to old 'seerflow.theme' key", async () => {
    const { useThemeStore } = await import("./theme");
    useThemeStore.getState().toggle();
    expect(localStorage.getItem("seerflow.theme")).toBeNull();
  });

  it("hydrates from localStorage 'seerflow-theme' on first access", async () => {
    localStorage.setItem("seerflow-theme", "light");
    const { useThemeStore } = await import("./theme");
    expect(useThemeStore.getState().theme).toBe("light");
    expect(document.documentElement.classList.contains("sf-light")).toBe(true);
  });

  it("dispatches seerflow-theme CustomEvent on toggle", async () => {
    const { useThemeStore } = await import("./theme");
    const events: CustomEvent[] = [];
    const listener = (e: Event) => events.push(e as CustomEvent);
    window.addEventListener("seerflow-theme", listener);
    useThemeStore.getState().toggle();
    window.removeEventListener("seerflow-theme", listener);
    expect(events).toHaveLength(1);
    expect(events[0].detail).toEqual({ light: true });
  });

  it("does NOT set data-theme attribute (legacy mechanism removed)", async () => {
    const { useThemeStore } = await import("./theme");
    useThemeStore.getState().toggle();
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });
});
