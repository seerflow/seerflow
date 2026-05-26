import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeToggle } from "./ThemeToggle";

describe("ThemeToggle", () => {
  beforeEach(() => {
    document.documentElement.classList.remove("sf-light");
    localStorage.clear();
  });

  it("renders Dark and Light buttons", () => {
    render(<ThemeToggle />);
    expect(screen.getByTitle("Dark")).toBeTruthy();
    expect(screen.getByTitle("Light")).toBeTruthy();
  });

  it("clicking Light button adds sf-light class to html", async () => {
    render(<ThemeToggle />);
    await userEvent.click(screen.getByTitle("Light"));
    expect(document.documentElement.classList.contains("sf-light")).toBe(true);
  });

  it("clicking Dark button removes sf-light class from html", async () => {
    document.documentElement.classList.add("sf-light");
    render(<ThemeToggle />);
    await userEvent.click(screen.getByTitle("Dark"));
    expect(document.documentElement.classList.contains("sf-light")).toBe(false);
  });
});
