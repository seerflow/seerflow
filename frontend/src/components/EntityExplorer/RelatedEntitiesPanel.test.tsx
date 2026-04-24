import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { RelatedEntitiesPanel } from "./RelatedEntitiesPanel";

const rel = (o: Partial<{ relation_type: string; entity_value: string; entity_uuid: string }>) => ({
  entity_uuid: o.entity_uuid ?? "uuid",
  entity_type: "user",
  entity_value: o.entity_value ?? "v",
  relation_type: o.relation_type ?? "authenticated_from",
});

describe("RelatedEntitiesPanel", () => {
  it("groups by relation_type with humanized labels", () => {
    render(<RelatedEntitiesPanel related={[rel({ relation_type: "authenticated_from" }), rel({ relation_type: "logged_into" })]} onNavigate={() => {}} />);
    expect(screen.getByText(/Authenticated from/i)).toBeInTheDocument();
    expect(screen.getByText(/Logged into/i)).toBeInTheDocument();
  });
  it("calls onNavigate on click", () => {
    const spy = vi.fn();
    render(<RelatedEntitiesPanel related={[rel({ entity_uuid: "x", entity_value: "bob" })]} onNavigate={spy} />);
    fireEvent.click(screen.getByText("bob"));
    expect(spy).toHaveBeenCalledWith("x");
  });
  it("renders empty state", () => {
    render(<RelatedEntitiesPanel related={[]} onNavigate={() => {}} />);
    expect(screen.getByText(/No related entities/i)).toBeInTheDocument();
  });

  // S-060.F2 — lock-in: render must not mutate the input array.
  it("does not mutate the input related[] array", () => {
    const related = [
      rel({ relation_type: "authenticated_from", entity_uuid: "u1", entity_value: "alice" }),
      rel({ relation_type: "authenticated_from", entity_uuid: "u2", entity_value: "10.0.0.5" }),
      rel({ relation_type: "logged_into", entity_uuid: "u3", entity_value: "web-01" }),
    ];
    const sameRef = related;
    const snapshot = JSON.parse(JSON.stringify(related));
    render(<RelatedEntitiesPanel related={related} onNavigate={() => {}} />);
    expect(related).toBe(sameRef);
    expect(related).toEqual(snapshot);
    expect(related).toHaveLength(3);
  });
});
