import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FeedbackHistory } from "./FeedbackHistory";
import type { FeedbackEvent } from "@/lib/types";

let nextId = 1;
const ev = (p: Partial<FeedbackEvent> = {}): FeedbackEvent => ({
  id: nextId++,
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

  it("tp/fp badges use brand tokens, not fixed light-palette literals (S-349)", () => {
    render(<FeedbackHistory items={[ev({ feedback: "tp" }), ev({ feedback: "fp" })]} />);
    const rows = screen.getAllByTestId("feedback-history-row");
    // Rows render in array order: rows[0] is the tp event, rows[1] the fp event.
    const tpBadge = rows[0].querySelector("span");
    const fpBadge = rows[1].querySelector("span");
    expect(fpBadge?.className).toContain("text-warn");
    expect(tpBadge?.className).toContain("text-info");
    for (const r of rows) {
      expect(r.className + (r.querySelector("span")?.className ?? "")).not.toMatch(
        /emerald-\d+|amber-\d+/,
      );
    }
  });
});
