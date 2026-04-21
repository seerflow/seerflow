import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach } from "vitest";
import { AddWidgetMenu } from "./AddWidgetMenu";
import { useLayoutStore, ALL_WIDGET_IDS, DEFAULT_WIDGETS } from "@/stores/layout";

beforeEach(() => useLayoutStore.getState().resetToDefault());

describe("AddWidgetMenu", () => {
  it("lists only widgets not currently on the grid", async () => {
    const user = userEvent.setup();
    const { findByText, queryByText, getByRole } = render(<AddWidgetMenu />);
    await user.click(getByRole("button", { name: /add widget/i }));
    expect(await findByText("ATT&CK coverage")).toBeInTheDocument();
    expect(await findByText("Source health")).toBeInTheDocument();
    expect(queryByText("Alert feed")).toBeNull();
  });

  it("adds the clicked widget to the layout store", async () => {
    const user = userEvent.setup();
    const { findByText, getByRole } = render(<AddWidgetMenu />);
    await user.click(getByRole("button", { name: /add widget/i }));
    await user.click(await findByText("ATT&CK coverage"));
    expect(useLayoutStore.getState().widgets).toContain("attackHeatmap");
  });

  it('shows "All widgets on the grid" label when every widget is mounted', async () => {
    const addWidget = useLayoutStore.getState().addWidget;
    for (const id of ALL_WIDGET_IDS) {
      if (!DEFAULT_WIDGETS.includes(id)) {
        addWidget(id);
      }
    }
    const user = userEvent.setup();
    const { getByRole, findByText } = render(<AddWidgetMenu />);
    await user.click(getByRole("button", { name: /add widget/i }));
    expect(await findByText("All widgets on the grid")).toBeInTheDocument();
  });
});
