import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { EntityGraph } from "./EntityGraph";
import type { EntityRelation } from "@/lib/types";

// jsdom does not implement pointer-capture; stub before each test.
beforeEach(() => {
  (globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
    class { observe() {} disconnect() {} unobserve() {} } as unknown as typeof ResizeObserver;
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.hasPointerCapture = vi.fn(() => false);
});

const focal = { uuid: "f", label: "alice@corp", type: "user" };
const oneRelated: EntityRelation[] = [
  { entity_uuid: "a", entity_value: "10.0.0.5", entity_type: "ip", relation_type: "authenticated_from" },
];

function getTransformGroup(container: HTMLElement): SVGGElement {
  const g = container.querySelector("svg > g");
  if (!g) throw new Error("transform <g> not found");
  return g as SVGGElement;
}

function parseTranslateScale(transform: string): { tx: number; ty: number; scale: number } {
  const t = /translate\(([-\d.]+)\s+([-\d.]+)\)/.exec(transform);
  const s = /scale\(([-\d.]+)\)/.exec(transform);
  return {
    tx: t ? Number.parseFloat(t[1]) : 0,
    ty: t ? Number.parseFloat(t[2]) : 0,
    scale: s ? Number.parseFloat(s[1]) : 1,
  };
}

describe("EntityGraph — base rendering", () => {
  it("renders focal + related nodes as circles", () => {
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={() => {}} />,
    );
    expect(container.querySelectorAll("circle").length).toBeGreaterThanOrEqual(2);
  });

  it("empty related renders focal + 'No related' label", () => {
    render(<EntityGraph focal={focal} related={[]} onNavigate={() => {}} />);
    expect(screen.getByText(/No related/i)).toBeInTheDocument();
  });

  it("caps at 100 nodes and shows warning when > 100 related", () => {
    const many: EntityRelation[] = Array.from({ length: 120 }, (_, i) => ({
      entity_uuid: `u${i}`, entity_value: `v${i}`, entity_type: "ip", relation_type: "has_ip",
    }));
    render(<EntityGraph focal={focal} related={many} onNavigate={() => {}} />);
    expect(screen.getByText(/Showing top 100/i)).toBeInTheDocument();
  });
});

describe("EntityGraph — click-vs-drag on satellite nodes", () => {
  it("click without movement → onNavigate", () => {
    const spy = vi.fn();
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={spy} />,
    );
    const satelliteGroup = container.querySelectorAll<SVGGElement>("g[data-node-id]")[0];
    fireEvent.pointerDown(satelliteGroup, { pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerUp(satelliteGroup, { pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.click(satelliteGroup);
    expect(spy).toHaveBeenCalledWith("a");
  });

  it("drag (>4 px) → onNavigate suppressed", () => {
    const spy = vi.fn();
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={spy} />,
    );
    const satelliteGroup = container.querySelectorAll<SVGGElement>("g[data-node-id]")[0];
    fireEvent.pointerDown(satelliteGroup, { pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(satelliteGroup, { pointerId: 1, clientX: 120, clientY: 110 });
    fireEvent.pointerUp(satelliteGroup, { pointerId: 1, clientX: 120, clientY: 110 });
    fireEvent.click(satelliteGroup);
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("EntityGraph — pan", () => {
  it("pointer drag on SVG background updates transform tx", () => {
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={() => {}} />,
    );
    const svg = container.querySelector("svg") as SVGSVGElement;
    fireEvent.pointerDown(svg, { pointerId: 2, clientX: 0, clientY: 0 });
    fireEvent.pointerMove(svg, { pointerId: 2, clientX: 50, clientY: 30 });
    fireEvent.pointerUp(svg, { pointerId: 2, clientX: 50, clientY: 30 });
    const t = parseTranslateScale(getTransformGroup(container).getAttribute("transform") ?? "");
    expect(t.tx).toBeCloseTo(50, 1);
    expect(t.ty).toBeCloseTo(30, 1);
  });
});

describe("EntityGraph — keyboard", () => {
  it("'+' zooms in", () => {
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={() => {}} />,
    );
    const wrapper = container.querySelector('[role="application"]') as HTMLDivElement;
    wrapper.focus();
    fireEvent.keyDown(wrapper, { key: "+" });
    const t = parseTranslateScale(getTransformGroup(container).getAttribute("transform") ?? "");
    expect(t.scale).toBeGreaterThan(1);
  });

  it("'-' zooms out (clamped at 0.5)", () => {
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={() => {}} />,
    );
    const wrapper = container.querySelector('[role="application"]') as HTMLDivElement;
    wrapper.focus();
    for (let i = 0; i < 10; i++) fireEvent.keyDown(wrapper, { key: "-" });
    const t = parseTranslateScale(getTransformGroup(container).getAttribute("transform") ?? "");
    expect(t.scale).toBeCloseTo(0.5, 5);
  });

  it("ArrowLeft pans (tx > 0)", () => {
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={() => {}} />,
    );
    const wrapper = container.querySelector('[role="application"]') as HTMLDivElement;
    wrapper.focus();
    fireEvent.keyDown(wrapper, { key: "ArrowLeft" });
    const t = parseTranslateScale(getTransformGroup(container).getAttribute("transform") ?? "");
    expect(t.tx).toBeGreaterThan(0);
  });

  it("'0' resets the view to identity", () => {
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={() => {}} />,
    );
    const wrapper = container.querySelector('[role="application"]') as HTMLDivElement;
    wrapper.focus();
    fireEvent.keyDown(wrapper, { key: "+" });
    fireEvent.keyDown(wrapper, { key: "ArrowLeft" });
    fireEvent.keyDown(wrapper, { key: "0" });
    const t = parseTranslateScale(getTransformGroup(container).getAttribute("transform") ?? "");
    expect(t).toEqual({ tx: 0, ty: 0, scale: 1 });
  });

  it("'Escape' blurs the wrapper", () => {
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={() => {}} />,
    );
    const wrapper = container.querySelector('[role="application"]') as HTMLDivElement;
    wrapper.focus();
    expect(document.activeElement).toBe(wrapper);
    fireEvent.keyDown(wrapper, { key: "Escape" });
    expect(document.activeElement).not.toBe(wrapper);
  });
});

describe("EntityGraph — Reset view button", () => {
  it("renders a Reset view button", () => {
    render(<EntityGraph focal={focal} related={oneRelated} onNavigate={() => {}} />);
    expect(screen.getByRole("button", { name: /reset graph view/i })).toBeInTheDocument();
  });

  it("click resets the transform", () => {
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={() => {}} />,
    );
    const wrapper = container.querySelector('[role="application"]') as HTMLDivElement;
    wrapper.focus();
    fireEvent.keyDown(wrapper, { key: "+" });
    fireEvent.keyDown(wrapper, { key: "ArrowLeft" });
    fireEvent.click(screen.getByRole("button", { name: /reset graph view/i }));
    const t = parseTranslateScale(getTransformGroup(container).getAttribute("transform") ?? "");
    expect(t).toEqual({ tx: 0, ty: 0, scale: 1 });
  });
});

describe("EntityGraph — tooltip", () => {
  it("pointer over a satellite shows the tooltip", () => {
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={() => {}} />,
    );
    const satelliteGroup = container.querySelectorAll<SVGGElement>("g[data-node-id]")[0];
    fireEvent.pointerMove(satelliteGroup, { pointerId: 3, clientX: 100, clientY: 100 });
    const tip = screen.getByRole("tooltip");
    expect(tip.textContent).toMatch(/IP/i);
    expect(tip.textContent).toMatch(/10\.0\.0\.5/);
    expect(tip.textContent).toMatch(/authenticated_from/);
  });

  it("pointer leave hides the tooltip", () => {
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={() => {}} />,
    );
    const satelliteGroup = container.querySelectorAll<SVGGElement>("g[data-node-id]")[0];
    fireEvent.pointerMove(satelliteGroup, { pointerId: 3, clientX: 100, clientY: 100 });
    fireEvent.pointerLeave(satelliteGroup);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});

describe("EntityGraph — sizing wrapper", () => {
  it("wrapper has h-full + min-h-0 and no min-h-[ class", () => {
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={() => {}} />,
    );
    const wrapper = container.querySelector('[role="application"]') as HTMLDivElement;
    expect(wrapper.className).toMatch(/h-full/);
    expect(wrapper.className).toMatch(/min-h-0/);
    expect(wrapper.className).not.toMatch(/min-h-\[/);
    expect(wrapper.className).not.toMatch(/h-80/);
  });
});

describe("EntityGraph — a11y", () => {
  it("wrapper has role=application + aria-roledescription", () => {
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={() => {}} />,
    );
    const wrapper = container.querySelector('[role="application"]') as HTMLDivElement;
    expect(wrapper.getAttribute("aria-roledescription")).toBe("interactive relationship graph");
    expect(wrapper.getAttribute("tabindex")).toBe("0");
  });

  it("svg retains role=img + aria-label", () => {
    const { container } = render(
      <EntityGraph focal={focal} related={oneRelated} onNavigate={() => {}} />,
    );
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("role")).toBe("img");
    expect(svg?.getAttribute("aria-label")).toMatch(/Relationship graph/i);
  });
});
