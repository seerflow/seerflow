import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FeedbackHistory } from "./FeedbackHistory";
import type { FeedbackEvent } from "@/lib/types";

const ev = (p: Partial<FeedbackEvent> = {}): FeedbackEvent => ({
  feedback: "tp",
  note: "",
  origin: "dashboard",
  submitted_at_ns: 1_700_000_000_000_000_000n,
  ...p,
});

describe("FeedbackHistory", () => {
  it("renders newest-first with badge + origin chip", () => {
    render(<FeedbackHistory items={[ev({ feedback: "fp", origin: "cli" }), ev()]} />);
    const rows = screen.getAllByTestId("feedback-history-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent(/fp/i);
    expect(rows[0]).toHaveTextContent(/cli/i);
  });

  it("empty list shows placeholder", () => {
    render(<FeedbackHistory items={[]} />);
    expect(screen.getByText(/no feedback yet/i)).toBeInTheDocument();
  });
});
