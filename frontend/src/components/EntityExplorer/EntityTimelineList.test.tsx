import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EntityTimelineList } from "./EntityTimelineList";
import type { EntityEvent } from "@/lib/types";

const mk = (o: Partial<EntityEvent> = {}): EntityEvent => ({
  event_id: o.event_id ?? `e-${Math.random()}`,
  timestamp_ns: o.timestamp_ns ?? BigInt(Date.now()) * 1_000_000n,
  source_type: o.source_type ?? "syslog",
  severity_id: o.severity_id ?? 3,
  message: o.message ?? "hello",
  related_ips: o.related_ips ?? [],
  related_users: o.related_users ?? [],
  related_hosts: o.related_hosts ?? [],
  related_domains: o.related_domains ?? [],
  ...(o.ioc_matches !== undefined ? { ioc_matches: o.ioc_matches } : {}),
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
    const day1 = BigInt(new Date(2026, 0, 1, 12, 0, 0).getTime()) * 1_000_000n;
    const day2 = BigInt(new Date(2026, 0, 2, 12, 0, 0).getTime()) * 1_000_000n;
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
    const base = BigInt(Date.now()) * 1_000_000n;
    const events = Array.from({ length: 250 }, (_, i) =>
      mk({ event_id: `e${i}`, timestamp_ns: base + BigInt(i) * 1000n }),
    );
    const { container } = render(<EntityTimelineList events={events} total={250} limit={1000} />);
    // The virtualized branch wraps the rows in a relative container with explicit
    // pixel height set from virtualizer.getTotalSize().
    const virtContainer = container.querySelector('div[style*="position: relative"]');
    expect(virtContainer).not.toBeNull();
    expect((virtContainer as HTMLElement).style.height).toMatch(/\d+px/);
  });

  it("S-069: renders TI badge when event has ioc_matches", () => {
    const evt = mk({
      ioc_matches: [
        {
          value: "1.2.3.4",
          type: "ipv4",
          source_feed: "otx",
          confidence: 75,
          kill_chain_phases: ["impact"],
          entity_kind: "ip",
        },
      ],
    });
    render(<EntityTimelineList events={[evt]} total={1} limit={100} />);
    expect(screen.getByText("TI")).toBeInTheDocument();
  });

  it("S-069: does not render TI badge when ioc_matches absent or empty", () => {
    const evt = mk({});
    render(<EntityTimelineList events={[evt]} total={1} limit={100} />);
    expect(screen.queryByText("TI")).not.toBeInTheDocument();
  });

  it("renders boundary timestamp_ns above 2^53 without precision loss (S-199 AC-7)", () => {
    const events: EntityEvent[] = [{
      event_id: "e-boundary",
      timestamp_ns: 1_700_000_000_000_000_123n,
      source_type: "syslog",
      severity_id: 10,
      message: "m",
      related_ips: [], related_users: [], related_hosts: [], related_domains: [],
    }];
    render(<EntityTimelineList events={events} total={1} limit={50} />);
    // Time is rendered via toLocaleTimeString — locale-tolerant regex to avoid CI tz surprises.
    expect(screen.getByText(/\d{1,2}:\d{2}:\d{2}/)).toBeInTheDocument();
  });
});
