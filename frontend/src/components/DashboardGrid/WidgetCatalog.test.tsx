import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import type { WidgetId } from "@/stores/layout";
import { WIDGET_CATALOG, getWidget } from "./WidgetCatalog";

describe("WidgetCatalog", () => {
  it("exposes all six registered widgets", () => {
    const ids = WIDGET_CATALOG.map((w) => w.id);
    expect(ids).toEqual([
      "alertFeed",
      "anomalyTimeline",
      "entityExplorer",
      "eventStream",
      "attackHeatmap",
      "sourceHealthPreview",
    ]);
  });

  it("getWidget returns the entry for known ids with the expected title/category", () => {
    expect(getWidget("alertFeed")?.title).toBe("Alert feed");
    expect(getWidget("alertFeed")?.category).toBe("core");
    expect(getWidget("sourceHealthPreview")?.category).toBe("optional");
    expect(getWidget("attackHeatmap")?.category).toBe("optional");
  });

  it("getWidget returns undefined for unknown ids", () => {
    expect(getWidget("bogus" as WidgetId)).toBeUndefined();
  });

  it("entityExplorer Component wrapper renders with a search combobox and entity detail region", () => {
    const entry = getWidget("entityExplorer");
    expect(entry).toBeDefined();
    const Component = entry!.Component;
    // EntityDetail returns null when no uuid is selected, which is the default
    // store state — the wrapper still mounts both children (EntitySearch
    // always renders, EntityDetail resolves to null). This asserts the wrapper
    // is callable and mounts the search child.
    const { container, getByRole } = render(<Component />);
    // EntitySearch renders a combobox input
    expect(getByRole("combobox")).toBeInTheDocument();
    // Outer wrapper shell applies the flex layout classes
    const wrapper = container.firstElementChild;
    expect(wrapper).not.toBeNull();
    expect(wrapper?.className).toContain("flex");
    expect(wrapper?.className).toContain("h-full");
    expect(wrapper?.className).toContain("flex-col");
  });
});
