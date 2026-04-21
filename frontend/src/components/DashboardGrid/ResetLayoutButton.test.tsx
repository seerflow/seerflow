import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach } from "vitest";
import { ResetLayoutButton } from "./ResetLayoutButton";
import { useLayoutStore } from "@/stores/layout";

beforeEach(() => {
  useLayoutStore.getState().resetToDefault();
});

describe("ResetLayoutButton", () => {
  it("opens a confirmation dialog and does nothing on cancel", async () => {
    const user = userEvent.setup();
    useLayoutStore.getState().addWidget("attackHeatmap");
    render(<ResetLayoutButton />);
    await user.click(screen.getByRole("button", { name: /reset layout/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(useLayoutStore.getState().widgets).toContain("attackHeatmap");
  });

  it("resets on confirm", async () => {
    const user = userEvent.setup();
    useLayoutStore.getState().addWidget("attackHeatmap");
    render(<ResetLayoutButton />);
    await user.click(screen.getByRole("button", { name: /reset layout/i }));
    await user.click(screen.getByRole("button", { name: /confirm/i }));
    expect(useLayoutStore.getState().widgets).not.toContain("attackHeatmap");
  });
});
