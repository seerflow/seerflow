import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EntityTimelineList } from "./EntityTimelineList";
import type { EntityEvent } from "@/lib/types";

const mk = (o: Partial<EntityEvent> = {}): EntityEvent => ({
  event_id: o.event_id ?? `e-${Math.random()}`,
  timestamp_ns: o.timestamp_ns ?? Date.now() * 1_000_000,
  source_type: o.source_type ?? "syslog",
  severity_id: o.severity_id ?? 3,
  message: o.message ?? "hello",
  related_ips: o.related_ips ?? [],
  related_users: o.related_users ?? [],
  related_hosts: o.related_hosts ?? [],
  related_domains: o.related_domains ?? [],
});

describe("EntityTimelineList", () => {
  it("renders empty state when events is empty", () => {
    render(<EntityTimelineList events={[]} total={0} limit={1000} />);
    expect(screen.getByText(/No events/i)).toBeInTheDocument();
  });
  it("renders events with source-type badge", () => {
    render(<EntityTimelineList events={[mk({ message: "m1", source_type: "zeek" })]} total={1} limit={1000} />);
    expect(screen.getByText("m1")).toBeInTheDocument();
    expect(screen.getByText("zeek")).toBeInTheDocument();
  });
  it("shows truncation warning when total === limit", () => {
    const many = Array.from({ length: 3 }, (_, i) => mk({ event_id: `e${i}` }));
    render(<EntityTimelineList events={many} total={1000} limit={1000} />);
    expect(screen.getByText(/may be truncated/i)).toBeInTheDocument();
  });

  it("renders a sticky day header per distinct day", () => {
    const day1 = new Date(2026, 0, 1, 12, 0, 0).getTime() * 1_000_000;
    const day2 = new Date(2026, 0, 2, 12, 0, 0).getTime() * 1_000_000;
    const events = [
      mk({ event_id: "a", timestamp_ns: day1, message: "first" }),
      mk({ event_id: "b", timestamp_ns: day2, message: "second" }),
    ];
    const { container } = render(<EntityTimelineList events={events} total={2} limit={1000} />);
    // Two day headers, two event rows
    const headers = container.querySelectorAll(".sticky");
    expect(headers.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("first")).toBeInTheDocument();
    expect(screen.getByText("second")).toBeInTheDocument();
  });

  it("uses virtualized branch when rows > 200", () => {
    const base = Date.now() * 1_000_000;
    const events = Array.from({ length: 250 }, (_, i) =>
      mk({ event_id: `e${i}`, timestamp_ns: base + i * 1000 }),
    );
    const { container } = render(<EntityTimelineList events={events} total={250} limit={1000} />);
    // The virtualized branch wraps the rows in a relative container with explicit
    // pixel height set from virtualizer.getTotalSize().
    const virtContainer = container.querySelector('div[style*="position: relative"]');
    expect(virtContainer).not.toBeNull();
    expect((virtContainer as HTMLElement).style.height).toMatch(/\d+px/);
  });
});
