import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EventRow } from "./EventRow";
import type { LiveEvent } from "@/lib/types";

const sample: LiveEvent = {
  event_id: "e1",
  timestamp_ns: 1_700_000_000_000_000_000,
  observed_ns: 1_700_000_000_000_000_001,
  severity_id: 4,
  severity_text: "WARN",
  source_type: "auth",
  message: "Failed login user=root ip=45.33.2.1",
  template_id: 17,
  entity_refs: ["u-1", "u-2"],
  entity_summary: { users: ["root"], ips: ["45.33.2.1"] },
};

describe("EventRow", () => {
  it("renders source, message, severity label, entity chips", () => {
    render(<EventRow event={sample} expanded={false} onToggle={() => undefined} />);
    expect(screen.getByText("auth")).toBeInTheDocument();
    expect(screen.getByText(/Failed login/)).toBeInTheDocument();
    expect(screen.getByText("WARN")).toBeInTheDocument();
    expect(screen.getByText("root")).toBeInTheDocument();
    expect(screen.getByText("45.33.2.1")).toBeInTheDocument();
  });

  it("truncates messages over 240 chars", () => {
    const long = "x".repeat(300);
    render(<EventRow event={{ ...sample, message: long }} expanded={false} onToggle={() => undefined} />);
    const msg = screen.getByTestId("event-message");
    expect(msg.textContent?.length).toBeLessThanOrEqual(243); // 240 + "…"
  });

  it("calls onToggle when row clicked", () => {
    const onToggle = vi.fn();
    render(<EventRow event={sample} expanded={false} onToggle={onToggle} />);
    fireEvent.click(screen.getByRole("button", { name: /event row/i }));
    expect(onToggle).toHaveBeenCalledWith("e1");
  });

  it("shows entity_summary as definition list when expanded", () => {
    render(<EventRow event={sample} expanded={true} onToggle={() => undefined} />);
    expect(screen.getByText(/template_id/i)).toBeInTheDocument();
    expect(screen.getByText("17")).toBeInTheDocument();
  });

  it("shows +N overflow chip when more than 3 entities", () => {
    const many: LiveEvent = {
      ...sample,
      entity_summary: { users: ["a", "b", "c", "d", "e"] },
    };
    render(<EventRow event={many} expanded={false} onToggle={() => undefined} />);
    expect(screen.getByText("+2")).toBeInTheDocument();
  });
});
