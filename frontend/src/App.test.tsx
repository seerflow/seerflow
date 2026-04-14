import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import App from "./App";
import { useThemeStore } from "@/stores/theme";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn().mockResolvedValue({ items: [] }), post: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

class NoopWS {
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  send() {}
  close() {}
}

describe("App shell", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", NoopWS as unknown as typeof WebSocket);
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    // Zustand store is a module-level singleton; reset to the same
    // initial state each test sees.
    useThemeStore.setState({ theme: "light" });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("renders the Seerflow wordmark", () => {
    render(<App />);
    const wordmark = screen.getByRole("img", { name: /seerflow/i });
    expect(wordmark).toBeInTheDocument();
    expect(wordmark).toHaveAttribute("src");
  });

  it("swaps the wordmark when the theme flips", () => {
    render(<App />);
    const lightSrc = (
      screen.getByRole("img", { name: /seerflow/i }) as HTMLImageElement
    ).src;
    fireEvent.click(screen.getByRole("button", { name: /toggle theme/i }));
    const darkSrc = (
      screen.getByRole("img", { name: /seerflow/i }) as HTMLImageElement
    ).src;
    expect(darkSrc).not.toBe(lightSrc);
  });

  it("renders the main region", () => {
    const { container } = render(<App />);
    expect(container.querySelector("main")).toBeInTheDocument();
  });

  it("theme toggle button flips data-theme", () => {
    render(<App />);
    const btn = screen.getByRole("button", { name: /toggle theme/i });
    fireEvent.click(btn);
    expect(document.documentElement.dataset.theme).toBe("dark");
    fireEvent.click(btn);
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
