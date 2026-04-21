import { render, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { WidgetFrame } from "./WidgetFrame";

describe("WidgetFrame", () => {
  it("renders the title and child body", () => {
    const { getByText } = render(
      <WidgetFrame title="Test" onRemove={() => undefined}>
        <div>body</div>
      </WidgetFrame>,
    );
    expect(getByText("Test")).toBeInTheDocument();
    expect(getByText("body")).toBeInTheDocument();
  });

  it("calls onRemove when the × button is clicked", () => {
    const onRemove = vi.fn();
    const { getByLabelText } = render(
      <WidgetFrame title="Test" onRemove={onRemove}>
        <div />
      </WidgetFrame>,
    );
    fireEvent.click(getByLabelText("Remove Test"));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it("title bar carries the drag-handle class for RGL and aria-label for a11y", () => {
    const { container, getByLabelText } = render(
      <WidgetFrame title="Test" onRemove={() => undefined}>
        <div />
      </WidgetFrame>,
    );
    expect(container.querySelector(".widget-drag-handle")).not.toBeNull();
    expect(getByLabelText("Drag Test")).toBeInTheDocument();
  });
});
