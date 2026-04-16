import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { DisconnectedBanner } from "./DisconnectedBanner";

describe("DisconnectedBanner", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("does not render when status is open", () => {
    render(<DisconnectedBanner status="open" />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("does not render when status is connecting", () => {
    render(<DisconnectedBanner status="connecting" />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("does not render before 3 s even when closed", () => {
    render(<DisconnectedBanner status="closed" />);
    act(() => { vi.advanceTimersByTime(2999); });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders banner at exactly 3 s when closed", () => {
    render(<DisconnectedBanner status="closed" />);
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByRole("status")).toHaveTextContent(/disconnected/i);
  });

  it("vanishes when status changes back to open", () => {
    const { rerender } = render(<DisconnectedBanner status="closed" />);
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByRole("status")).toBeInTheDocument();
    rerender(<DisconnectedBanner status="open" />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
