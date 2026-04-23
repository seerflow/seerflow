import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { DisconnectedBanner } from "./DisconnectedBanner";
import * as bus from "@/lib/wsBus";
import type { WsStatus } from "@/lib/types";

function emitStatus(status: WsStatus): void {
  bus.emit({ type: "__status", status });
}

describe("DisconnectedBanner (wsBus)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    bus._clearAllForTests();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not render when status is open", () => {
    render(<DisconnectedBanner />);
    act(() => { emitStatus("open"); });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("does not render when status is connecting", () => {
    render(<DisconnectedBanner />);
    act(() => { emitStatus("connecting"); });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("does not render before 3 s even when closed", () => {
    render(<DisconnectedBanner />);
    act(() => { emitStatus("closed"); });
    act(() => { vi.advanceTimersByTime(2999); });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders banner at exactly 3 s when closed", () => {
    render(<DisconnectedBanner />);
    act(() => { emitStatus("closed"); });
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByRole("status")).toHaveTextContent(/disconnected/i);
  });

  it("vanishes when status changes back to open after being shown", () => {
    render(<DisconnectedBanner />);
    act(() => { emitStatus("closed"); });
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByRole("status")).toBeInTheDocument();
    act(() => { emitStatus("open"); });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("unsubscribes from bus on unmount (no update-after-unmount warning)", () => {
    const { unmount } = render(<DisconnectedBanner />);
    unmount();
    // Emitting after unmount must not throw or trigger a React update warning.
    expect(() => {
      act(() => { emitStatus("closed"); });
      act(() => { vi.advanceTimersByTime(3000); });
    }).not.toThrow();
  });

  it("accepts a custom debounceMs prop for faster testing in callers", () => {
    render(<DisconnectedBanner debounceMs={10} />);
    act(() => { emitStatus("closed"); });
    act(() => { vi.advanceTimersByTime(10); });
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});
