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
});
