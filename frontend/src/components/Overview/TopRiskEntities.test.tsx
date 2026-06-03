import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { TopRiskEntities, type RiskEntity } from "./TopRiskEntities";

vi.mock("@/components/ui/primitives", () => ({
  EntityGlyph: ({ type }: { type: string }) => (
    <span data-testid={`entity-glyph-${type}`} />
  ),
  RiskBar: ({ value }: { value: number }) => (
    <div data-testid="risk-bar" data-value={value} />
  ),
  riskLevelFromValue: (v: number) => (v >= 0.8 ? "crit" : v >= 0.6 ? "warn" : "accent"),
}));

const makeEntity = (overrides: Partial<RiskEntity> = {}): RiskEntity => ({
  id: "ent-1",
  name: "root@10.0.1.42",
  kind: "user",
  risk: 0.94,
  eventCount: 1820,
  alertCount: 4,
  ...overrides,
});

describe("TopRiskEntities", () => {
  it("renders the section heading", () => {
    render(<TopRiskEntities entities={[]} />);
    expect(screen.getByText("Top risk entities")).toBeInTheDocument();
  });

  it("renders 'last 24h' time window label", () => {
    render(<TopRiskEntities entities={[]} />);
    expect(screen.getByText("last 24h")).toBeInTheDocument();
  });

  it("renders empty state when no entities", () => {
    render(<TopRiskEntities entities={[]} />);
    expect(screen.getByTestId("top-entities-empty")).toBeInTheDocument();
  });

  it("renders entity rows", () => {
    const entities = [makeEntity(), makeEntity({ id: "ent-2", name: "svc-deploy", kind: "service" })];
    render(<TopRiskEntities entities={entities} />);
    expect(screen.getAllByTestId(/entity-row-/)).toHaveLength(2);
  });

  it("renders entity name in mono", () => {
    render(<TopRiskEntities entities={[makeEntity()]} />);
    expect(screen.getByText("root@10.0.1.42")).toBeInTheDocument();
  });

  it("renders entity kind label uppercase", () => {
    render(<TopRiskEntities entities={[makeEntity()]} />);
    expect(screen.getByTestId("entity-kind-ent-1")).toHaveTextContent("user");
  });

  it("renders risk score", () => {
    render(<TopRiskEntities entities={[makeEntity()]} />);
    expect(screen.getByText("0.94")).toBeInTheDocument();
  });

  it("renders RiskBar for each entity", () => {
    const entities = [makeEntity(), makeEntity({ id: "ent-2", name: "svc-deploy", kind: "service", risk: 0.88 })];
    render(<TopRiskEntities entities={entities} />);
    const bars = screen.getAllByTestId("risk-bar");
    expect(bars).toHaveLength(2);
    expect(bars[0]).toHaveAttribute("data-value", "0.94");
  });

  it("renders event count and alert count", () => {
    render(<TopRiskEntities entities={[makeEntity()]} />);
    expect(screen.getByText(/1,820 ev/)).toBeInTheDocument();
    expect(screen.getByText(/4a/)).toBeInTheDocument();
  });

  it("renders EntityGlyph with correct type", () => {
    render(<TopRiskEntities entities={[makeEntity({ kind: "host" })]} />);
    expect(screen.getByTestId("entity-glyph-host")).toBeInTheDocument();
  });

  it("renders risk score in crit color for risk ≥ 0.8", () => {
    render(<TopRiskEntities entities={[makeEntity({ risk: 0.94 })]} />);
    const score = screen.getByTestId("risk-score-ent-1");
    expect(score).toHaveAttribute("data-level", "crit");
  });

  it("renders risk score in warn color for risk 0.6–0.8", () => {
    render(<TopRiskEntities entities={[makeEntity({ id: "ent-warn", risk: 0.71 })]} />);
    const score = screen.getByTestId("risk-score-ent-warn");
    expect(score).toHaveAttribute("data-level", "warn");
  });
});
