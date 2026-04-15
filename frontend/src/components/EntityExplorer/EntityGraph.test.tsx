import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { EntityGraph } from "./EntityGraph";

beforeEach(() => {
  // jsdom stubs
  (globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
    class { observe() {} disconnect() {} unobserve() {} } as unknown as typeof ResizeObserver;
});

describe("EntityGraph", () => {
  it("renders focal + related nodes as circles", () => {
    const { container } = render(
      <EntityGraph
        focal={{ uuid: "f", label: "focal", type: "user" }}
        related={[{ entity_uuid: "a", entity_value: "a", entity_type: "ip", relation_type: "authenticated_from" }]}
        onNavigate={() => {}}
      />,
    );
    expect(container.querySelectorAll("circle").length).toBeGreaterThanOrEqual(2);
  });
  it("empty related renders focal + 'No related' label", () => {
    render(
      <EntityGraph focal={{ uuid: "f", label: "focal", type: "user" }} related={[]} onNavigate={() => {}} />,
    );
    expect(screen.getByText(/No related/i)).toBeInTheDocument();
  });
  it("clicks non-focal node → calls onNavigate", () => {
    const spy = vi.fn();
    const { container } = render(
      <EntityGraph
        focal={{ uuid: "f", label: "focal", type: "user" }}
        related={[{ entity_uuid: "a", entity_value: "a", entity_type: "ip", relation_type: "has_ip" }]}
        onNavigate={spy}
      />,
    );
    const circles = container.querySelectorAll("circle");
    fireEvent.click(circles[1]); // related node
    expect(spy).toHaveBeenCalledWith("a");
  });
  it("caps at 100 nodes and shows warning when > 100 related", () => {
    const many = Array.from({ length: 120 }, (_, i) => ({
      entity_uuid: `u${i}`, entity_value: `v${i}`, entity_type: "ip", relation_type: "has_ip",
    }));
    render(
      <EntityGraph focal={{ uuid: "f", label: "focal", type: "user" }} related={many} onNavigate={() => {}} />,
    );
    expect(screen.getByText(/Showing top 100/i)).toBeInTheDocument();
  });
});
