import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AlertsPaginationFooter } from "./AlertsPaginationFooter";

describe("AlertsPaginationFooter", () => {
  it("shows the X–Y of N · page n/m summary", () => {
    render(
      <AlertsPaginationFooter
        total={178}
        page={1}
        rowsPerPage={50}
        onPageChange={() => {}}
        onRowsPerPageChange={() => {}}
      />,
    );
    expect(screen.getByTestId("alerts-page-summary")).toHaveTextContent(
      "showing 1–50 of 178 · page 1 / 4",
    );
  });

  it("computes the last partial page bounds", () => {
    render(
      <AlertsPaginationFooter
        total={178}
        page={4}
        rowsPerPage={50}
        onPageChange={() => {}}
        onRowsPerPageChange={() => {}}
      />,
    );
    expect(screen.getByTestId("alerts-page-summary")).toHaveTextContent(
      "showing 151–178 of 178 · page 4 / 4",
    );
  });

  it("handles an empty set gracefully", () => {
    render(
      <AlertsPaginationFooter
        total={0}
        page={1}
        rowsPerPage={50}
        onPageChange={() => {}}
        onRowsPerPageChange={() => {}}
      />,
    );
    expect(screen.getByTestId("alerts-page-summary")).toHaveTextContent(
      "showing 0–0 of 0 · page 1 / 1",
    );
  });

  it("renders rows-per-page options and fires the change", () => {
    const onRows = vi.fn();
    render(
      <AlertsPaginationFooter
        total={178}
        page={1}
        rowsPerPage={50}
        onPageChange={() => {}}
        onRowsPerPageChange={onRows}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "100" }));
    expect(onRows).toHaveBeenCalledWith(100);
  });

  it("advances the page with the next button", () => {
    const onPage = vi.fn();
    render(
      <AlertsPaginationFooter
        total={178}
        page={1}
        rowsPerPage={50}
        onPageChange={onPage}
        onRowsPerPageChange={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "›" }));
    expect(onPage).toHaveBeenCalledWith(2);
  });

  it("disables previous on the first page and next on the last", () => {
    const { rerender } = render(
      <AlertsPaginationFooter
        total={60}
        page={1}
        rowsPerPage={50}
        onPageChange={() => {}}
        onRowsPerPageChange={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "‹" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "›" })).toBeEnabled();

    rerender(
      <AlertsPaginationFooter
        total={60}
        page={2}
        rowsPerPage={50}
        onPageChange={() => {}}
        onRowsPerPageChange={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "›" })).toBeDisabled();
  });
});
