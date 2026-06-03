import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Topbar } from "./Topbar";

// ThemeToggle uses zustand store — works fine in jsdom
describe("Topbar", () => {
  it("renders breadcrumb segments", () => {
    render(<Topbar breadcrumb={["Workspace", "Overview"]} />);
    expect(screen.getByText("Workspace")).toBeInTheDocument();
    expect(screen.getByText("Overview")).toBeInTheDocument();
  });

  it("renders the ⌘K hint", () => {
    render(<Topbar breadcrumb={["Workspace", "Overview"]} />);
    expect(screen.getByText("⌘K")).toBeInTheDocument();
  });

  it("renders the search placeholder text", () => {
    render(<Topbar breadcrumb={["Workspace", "Overview"]} />);
    expect(
      screen.getByText(/jump to entity|rule|event/i),
    ).toBeInTheDocument();
  });

  it("renders time-window selector text", () => {
    render(<Topbar breadcrumb={["Workspace", "Overview"]} />);
    expect(screen.getByText(/last 15m/i)).toBeInTheDocument();
  });

  it("renders notifications bell (aria-label)", () => {
    render(<Topbar breadcrumb={["Workspace", "Overview"]} />);
    expect(screen.getByLabelText(/notifications/i)).toBeInTheDocument();
  });

  it("renders avatar element", () => {
    const { container } = render(<Topbar breadcrumb={["Workspace", "Overview"]} />);
    expect(container.querySelector("[data-testid='user-avatar']")).toBeInTheDocument();
  });

  it("renders ThemeToggle (dark/light buttons)", () => {
    render(<Topbar breadcrumb={["Workspace", "Overview"]} />);
    expect(screen.getByTitle("Dark")).toBeInTheDocument();
    expect(screen.getByTitle("Light")).toBeInTheDocument();
  });

  it("renders breadcrumb separator for multi-segment breadcrumbs", () => {
    render(<Topbar breadcrumb={["Workspace", "Alerts", "Detail"]} />);
    // Separators (/) between segments
    const separators = screen.getAllByText("/");
    expect(separators.length).toBeGreaterThanOrEqual(1);
  });

  it("calls onCommandK when search field is clicked", () => {
    const onCommandK = vi.fn();
    render(<Topbar breadcrumb={["Workspace", "Overview"]} onCommandK={onCommandK} />);
    const searchField = screen.getByRole("button", { name: /command search/i });
    searchField.click();
    expect(onCommandK).toHaveBeenCalled();
  });
});
