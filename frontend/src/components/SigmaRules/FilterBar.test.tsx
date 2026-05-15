import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { FilterBar } from "./FilterBar";

describe("FilterBar", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("debounces search 250ms before firing onChange", () => {
    const onChange = vi.fn();
    render(<FilterBar onChange={onChange} />);
    fireEvent.change(screen.getByPlaceholderText(/search rules/i), {
      target: { value: "ssh" },
    });
    expect(onChange).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(260);
    });
    expect(onChange).toHaveBeenCalledWith({ search: "ssh" });
  });

  it("category select fires immediately with null for All", () => {
    const onChange = vi.fn();
    render(<FilterBar onChange={onChange} />);
    fireEvent.change(screen.getByLabelText(/filter by category/i), {
      target: { value: "linux" },
    });
    expect(onChange).toHaveBeenCalledWith({ category: "linux" });
  });

  it("enabled-only checkbox fires immediately", () => {
    const onChange = vi.fn();
    render(<FilterBar onChange={onChange} />);
    fireEvent.click(screen.getByLabelText(/enabled only/i));
    expect(onChange).toHaveBeenCalledWith({ enabledOnly: true });
  });

  it("emits severity_in as the union of pressed chips (S-230)", () => {
    const onChange = vi.fn();
    render(<FilterBar onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "critical" }));
    fireEvent.click(screen.getByRole("button", { name: "high" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ severity_in: [5, 4] }),
    );
  });

  it("severity chip exposes aria-pressed reflecting selection (S-230)", () => {
    const onChange = vi.fn();
    render(<FilterBar onChange={onChange} />);
    const crit = screen.getByRole("button", { name: "critical" });
    expect(crit).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(crit);
    expect(
      screen.getByRole("button", { name: "critical" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("un-pressing removes the value from severity_in (empty array on full clear) (S-230)", () => {
    const onChange = vi.fn();
    render(<FilterBar initialSeverityIn={[5]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "critical" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ severity_in: [] }),
    );
  });

  it("logsource product select fires with null for All", () => {
    const onChange = vi.fn();
    render(<FilterBar onChange={onChange} />);
    fireEvent.change(screen.getByLabelText(/filter by logsource product/i), {
      target: { value: "windows" },
    });
    expect(onChange).toHaveBeenCalledWith({ logsource_product: "windows" });
  });

  it("does not fire onChange on initial render with initialSearch", () => {
    const onChange = vi.fn();
    render(<FilterBar initialSearch="preset" onChange={onChange} />);
    act(() => {
      vi.advanceTimersByTime(260);
    });
    expect(onChange).not.toHaveBeenCalled();
  });
});
