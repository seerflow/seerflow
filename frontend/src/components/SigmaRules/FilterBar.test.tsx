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

  it("does not fire onChange on initial render with initialSearch", () => {
    const onChange = vi.fn();
    render(<FilterBar initialSearch="preset" onChange={onChange} />);
    act(() => {
      vi.advanceTimersByTime(260);
    });
    expect(onChange).not.toHaveBeenCalled();
  });
});
