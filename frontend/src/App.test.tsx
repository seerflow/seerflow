import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import App from "./App";

describe("App shell", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("renders the Seerflow wordmark", () => {
    render(<App />);
    expect(screen.getByText(/seerflow/i)).toBeInTheDocument();
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
