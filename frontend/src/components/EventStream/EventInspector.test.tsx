import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EventInspector } from "./EventInspector";
import type { LiveEvent } from "@/lib/types";

const sample: LiveEvent = {
  event_id: "evt-abc",
  timestamp_ns: 1_700_000_000_000_000_000n,
  observed_ns:  1_700_000_001_500_000_000n,
  severity_id: 5,
  severity_text: "ERROR",
  source_type: "nginx",
  message: "Failed password for root",
  template_id: 42,
  entity_refs: [],
  entity_summary: {
    hosts: ["web-01"],
    ips: ["192.168.1.1"],
  },
};

describe("EventInspector", () => {
  it("shows placeholder when no event selected", () => {
    render(<EventInspector event={null} />);
    expect(screen.getByText(/select an event to inspect/i)).toBeInTheDocument();
  });

  it("shows 'Parsed event' section title when event provided", () => {
    render(<EventInspector event={sample} />);
    expect(screen.getByText(/parsed event/i)).toBeInTheDocument();
  });

  it("shows 'Entities extracted' section title", () => {
    render(<EventInspector event={sample} />);
    expect(screen.getByText(/entities extracted/i)).toBeInTheDocument();
  });

  it("shows 'Raw payload' section title", () => {
    render(<EventInspector event={sample} />);
    expect(screen.getByText(/raw payload/i)).toBeInTheDocument();
  });

  it("shows 'Receiver' section title", () => {
    render(<EventInspector event={sample} />);
    expect(screen.getByText(/receiver/i)).toBeInTheDocument();
  });

  it("shows severity badge with data-testid=inspector-severity", () => {
    render(<EventInspector event={sample} />);
    const badge = screen.getByTestId("inspector-severity");
    expect(badge).toHaveTextContent("ERROR");
  });

  it("shows event_id in parsed section", () => {
    render(<EventInspector event={sample} />);
    expect(screen.getAllByText(/evt-abc/).length).toBeGreaterThan(0);
  });

  it("shows message in parsed section", () => {
    render(<EventInspector event={sample} />);
    expect(screen.getAllByText(/Failed password for root/).length).toBeGreaterThan(0);
  });

  it("shows entity rows with data-testid=inspector-entity-row", () => {
    render(<EventInspector event={sample} />);
    const rows = screen.getAllByTestId("inspector-entity-row");
    expect(rows.length).toBeGreaterThan(0);
  });

  it("shows host entity value", () => {
    render(<EventInspector event={sample} />);
    const rows = screen.getAllByTestId("inspector-entity-row");
    const texts = rows.map((r) => r.textContent).join(" ");
    expect(texts).toMatch(/web-01/);
  });

  it("shows raw JSON with data-testid=inspector-raw", () => {
    render(<EventInspector event={sample} />);
    const raw = screen.getByTestId("inspector-raw");
    expect(raw.textContent).toMatch(/evt-abc/);
  });

  it("shows source_type in receiver section", () => {
    render(<EventInspector event={sample} />);
    expect(screen.getAllByText(/nginx/).length).toBeGreaterThan(0);
  });

  it("shows pipeline timing in ms (observed_ns - timestamp_ns) / 1e6", () => {
    render(<EventInspector event={sample} />);
    // observed_ns - timestamp_ns = 1_500_000_000 ns = 1500 ms
    const matches = screen.getAllByText(/1500/);
    expect(matches.length).toBeGreaterThan(0);
  });

  it("shows CRIT severity badge variant for severity_id >= 6", () => {
    const crit = { ...sample, severity_id: 7, severity_text: "FATAL" };
    render(<EventInspector event={crit} />);
    expect(screen.getByTestId("inspector-severity")).toHaveTextContent("FATAL");
  });

  it("shows empty entities gracefully (no crash)", () => {
    const noEntities = { ...sample, entity_summary: {} };
    render(<EventInspector event={noEntities} />);
    expect(screen.getByText(/entities extracted/i)).toBeInTheDocument();
  });
});
