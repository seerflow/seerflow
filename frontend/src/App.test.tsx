import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import App from "./App";

describe("App shell", () => {
  it("renders the Seerflow wordmark", () => {
    render(<App />);
    expect(screen.getByText(/seerflow/i)).toBeInTheDocument();
  });

  it("renders the placeholder dashboard card", () => {
    render(<App />);
    expect(screen.getByText(/dashboard coming online/i)).toBeInTheDocument();
  });
});
