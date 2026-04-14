import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FilterBar } from "./FilterBar";

describe("FilterBar", () => {
  it("toggling a severity chip calls onChange with new Set", () => {
    const onChange = vi.fn();
    render(<FilterBar
      filter={{severities: new Set(), types: new Set(), sources: new Set(), tactics: new Set()}}
      sources={["syslog"]} tactics={["TA0001"]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Critical" }));
    expect(onChange).toHaveBeenCalledWith({severities: new Set(["critical"])});
  });
});
