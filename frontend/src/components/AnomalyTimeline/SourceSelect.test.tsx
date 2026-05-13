import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SourceSelect } from "./SourceSelect";

describe("SourceSelect", () => {
  it("renders a combobox with the current value label", () => {
    render(<SourceSelect value={null} options={["syslog", "otlp"]} onChange={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: /source filter/i })).toBeInTheDocument();
  });

  it("shows the current value when set", () => {
    render(<SourceSelect value={"syslog"} options={["syslog", "otlp"]} onChange={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: /source filter/i })).toHaveTextContent("syslog");
  });

  it("defaults to All sources when value is null", () => {
    render(<SourceSelect value={null} options={["syslog", "otlp"]} onChange={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: /source filter/i })).toHaveTextContent(/all sources/i);
  });

  it("opens the dropdown and exposes options", async () => {
    const user = userEvent.setup();
    render(<SourceSelect value={null} options={["syslog", "otlp"]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("combobox", { name: /source filter/i }));
    expect(screen.getByRole("option", { name: "All sources" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "syslog" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "otlp" })).toBeInTheDocument();
  });

  it("calls onChange with null when All sources picked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<SourceSelect value={"syslog"} options={["syslog", "otlp"]} onChange={onChange} />);
    await user.click(screen.getByRole("combobox", { name: /source filter/i }));
    await user.click(screen.getByRole("option", { name: "All sources" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("calls onChange with the option string for concrete sources", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<SourceSelect value={null} options={["syslog", "otlp"]} onChange={onChange} />);
    await user.click(screen.getByRole("combobox", { name: /source filter/i }));
    await user.click(screen.getByRole("option", { name: "otlp" }));
    expect(onChange).toHaveBeenCalledWith("otlp");
  });

  it("marks the selected option with aria-selected=true and others with false (value=null)", async () => {
    const user = userEvent.setup();
    render(<SourceSelect value={null} options={["syslog", "otlp"]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("combobox", { name: /source filter/i }));
    // Radix SelectItem renders role="option" and owns aria-selected on the
    // currently-selected item; we assert that contract directly.
    expect(screen.getByRole("option", { name: "All sources" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      screen.getByRole("option", { name: "syslog" }).getAttribute("aria-selected"),
    ).not.toBe("true");
    expect(
      screen.getByRole("option", { name: "otlp" }).getAttribute("aria-selected"),
    ).not.toBe("true");
  });

  it("marks the selected option with aria-selected=true when a concrete source is selected", async () => {
    const user = userEvent.setup();
    render(<SourceSelect value={"syslog"} options={["syslog", "otlp"]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("combobox", { name: /source filter/i }));
    expect(screen.getByRole("option", { name: "syslog" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      screen.getByRole("option", { name: "All sources" }).getAttribute("aria-selected"),
    ).not.toBe("true");
    expect(
      screen.getByRole("option", { name: "otlp" }).getAttribute("aria-selected"),
    ).not.toBe("true");
  });
});
