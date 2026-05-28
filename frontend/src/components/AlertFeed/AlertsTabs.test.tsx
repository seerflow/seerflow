import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AlertsTabs, type AlertTab } from "./AlertsTabs";

const counts = { open: 17, triaging: 6, resolved: 124, suppressed: 31, all: 178 };

describe("AlertsTabs", () => {
  it("renders the five tabs with counts", () => {
    render(<AlertsTabs active="open" counts={counts} onSelect={() => {}} />);
    for (const t of ["Open", "Triaging", "Resolved", "Suppressed", "All"]) {
      expect(screen.getByRole("tab", { name: new RegExp(t) })).toBeInTheDocument();
    }
    expect(screen.getByRole("tab", { name: /Open/ })).toHaveTextContent("17");
    expect(screen.getByRole("tab", { name: /All/ })).toHaveTextContent("178");
  });

  it("marks the active tab selected", () => {
    render(<AlertsTabs active="triaging" counts={counts} onSelect={() => {}} />);
    expect(screen.getByRole("tab", { name: /Triaging/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /Open/ })).toHaveAttribute("aria-selected", "false");
  });

  it("renders the active-tab accent underline (not clobbered by a border reset)", () => {
    render(<AlertsTabs active="open" counts={counts} onSelect={() => {}} />);
    const active = screen.getByRole("tab", { name: /Open/ });
    const inactive = screen.getByRole("tab", { name: /Resolved/ });
    // The 2px accent bottom border is the active affordance. The other three
    // edges are reset with explicit `borderTop/Left/Right: none` rather than a
    // trailing `border: none` shorthand, which would clobber the bottom edge.
    expect(active.style.borderBottom).toBe("2px solid var(--accent)");
    expect(inactive.style.borderBottom).toBe("2px solid transparent");
    // No `border` shorthand is set (would have reset the bottom edge).
    expect(active.style.border).toBe("");
  });

  it("fires onSelect with the tab key", () => {
    const onSelect = vi.fn();
    render(<AlertsTabs active="open" counts={counts} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("tab", { name: /Resolved/ }));
    expect(onSelect).toHaveBeenCalledWith<[AlertTab]>("resolved");
  });
});
