import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import App from "./App";
import { useThemeStore } from "@/stores/theme";

describe("App shell", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    // Zustand store is a module-level singleton; reset to the same
    // initial state each test sees.
    useThemeStore.setState({ theme: "light" });
  });

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

  it("renders the placeholder dashboard card", () => {
    render(<App />);
    expect(screen.getByText(/dashboard coming online/i)).toBeInTheDocument();
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
