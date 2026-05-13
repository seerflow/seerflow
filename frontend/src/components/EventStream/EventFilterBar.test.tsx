import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EventFilterBar } from "./EventFilterBar";
import type { EventFilter } from "@/lib/types";

const empty: EventFilter = { sources: new Set(), minSeverity: 0, templateIds: new Set() };

describe("EventFilterBar", () => {
  it("renders source chips for each known source", () => {
    render(<EventFilterBar filter={empty} knownSources={["auth", "syslog"]} onChange={() => undefined} />);
    expect(screen.getByRole("button", { name: "auth" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "syslog" })).toBeInTheDocument();
  });

  it("source chips carry aria-pressed reflecting the filter selection state", () => {
    const selected: EventFilter = {
      sources: new Set(["auth"]),
      minSeverity: 0,
      templateIds: new Set(),
    };
    render(<EventFilterBar filter={selected} knownSources={["auth", "syslog"]} onChange={() => undefined} />);
    const authChip = screen.getByRole("button", { name: "auth" });
    const syslogChip = screen.getByRole("button", { name: "syslog" });
    expect(authChip).toHaveAttribute("aria-pressed", "true");
    expect(syslogChip).toHaveAttribute("aria-pressed", "false");
  });

  it("toggling a source chip emits onChange with updated set", () => {
    const onChange = vi.fn();
    render(<EventFilterBar filter={empty} knownSources={["auth"]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "auth" }));
    expect(onChange).toHaveBeenCalledTimes(1);
    const arg = onChange.mock.calls[0][0] as Partial<EventFilter>;
    expect([...(arg.sources ?? new Set())]).toEqual(["auth"]);
  });

  it("severity select emits minSeverity change", () => {
    const onChange = vi.fn();
    render(<EventFilterBar filter={empty} knownSources={[]} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText(/min severity/i), { target: { value: "4" } });
    expect(onChange).toHaveBeenCalledWith({ minSeverity: 4 });
  });

  it("template id chip input adds valid integer", () => {
    const onChange = vi.fn();
    render(<EventFilterBar filter={empty} knownSources={[]} onChange={onChange} />);
    const input = screen.getByLabelText(/template id/i);
    fireEvent.change(input, { target: { value: "17" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith({ templateIds: new Set([17]) });
  });

  it("template id chip input rejects non-integer silently", () => {
    const onChange = vi.fn();
    render(<EventFilterBar filter={empty} knownSources={[]} onChange={onChange} />);
    const input = screen.getByLabelText(/template id/i);
    fireEvent.change(input, { target: { value: "abc" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();
  });
});
