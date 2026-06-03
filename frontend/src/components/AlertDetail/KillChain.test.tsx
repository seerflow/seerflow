import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { KillChain, KILL_CHAIN_STAGES, type KillChainStageState } from "./KillChain";

describe("KillChain", () => {
  it("renders all 7 stage nodes", () => {
    render(<KillChain activeIdx={2} stages={[]} />);
    KILL_CHAIN_STAGES.forEach((s) => {
      expect(screen.getByText(s.label)).toBeInTheDocument();
    });
  });

  it("applies done state to stages before activeIdx", () => {
    render(<KillChain activeIdx={3} stages={[]} />);
    const doneNodes = screen.getAllByTestId("kc-stage-done");
    expect(doneNodes.length).toBe(3);
  });

  it("applies active state to the stage at activeIdx", () => {
    render(<KillChain activeIdx={1} stages={[]} />);
    const activeNode = screen.getByTestId("kc-stage-active");
    expect(activeNode).toBeInTheDocument();
    expect(activeNode).toHaveAttribute("aria-current", "step");
  });

  it("applies imminent state to the stage after activeIdx", () => {
    render(<KillChain activeIdx={2} stages={[]} />);
    const imminentNode = screen.getByTestId("kc-stage-imminent");
    expect(imminentNode).toBeInTheDocument();
  });

  it("applies pending state to remaining stages", () => {
    render(<KillChain activeIdx={2} stages={[]} />);
    const pendingNodes = screen.getAllByTestId("kc-stage-pending");
    expect(pendingNodes.length).toBe(3);
  });

  it("shows TA-id for each stage", () => {
    render(<KillChain activeIdx={0} stages={[]} />);
    KILL_CHAIN_STAGES.forEach((s) => {
      expect(screen.getByText(s.taId)).toBeInTheDocument();
    });
  });

  it("displays relative time for the active stage when provided", () => {
    const stages: Array<{ relativeTime?: string }> = [
      {},
      { relativeTime: "5m ago" },
      {},
      {},
      {},
      {},
      {},
    ];
    render(<KillChain activeIdx={1} stages={stages} />);
    expect(screen.getByText("5m ago")).toBeInTheDocument();
  });

  it("renders without errors when activeIdx is undefined (all pending)", () => {
    render(<KillChain stages={[]} />);
    const pendingNodes = screen.getAllByTestId("kc-stage-pending");
    expect(pendingNodes.length).toBe(7);
  });

  it("marks activeIdx=0 with no done stages", () => {
    render(<KillChain activeIdx={0} stages={[]} />);
    expect(screen.queryAllByTestId("kc-stage-done")).toHaveLength(0);
    expect(screen.getByTestId("kc-stage-active")).toBeInTheDocument();
  });

  it("marks activeIdx=6 with 6 done stages and no pending", () => {
    render(<KillChain activeIdx={6} stages={[]} />);
    expect(screen.queryAllByTestId("kc-stage-done")).toHaveLength(6);
    expect(screen.queryAllByTestId("kc-stage-pending")).toHaveLength(0);
    expect(screen.queryAllByTestId("kc-stage-imminent")).toHaveLength(0);
  });

  it("has accessible role for each stage node", () => {
    render(<KillChain activeIdx={2} stages={[]} />);
    const listItems = screen.getAllByRole("listitem");
    expect(listItems.length).toBe(7);
  });

  it("lays the stages out in a horizontal grid (mockup fidelity)", () => {
    render(<KillChain activeIdx={2} stages={[]} />);
    const list = screen.getByRole("list", { name: /kill chain/i });
    expect(list).toHaveStyle({ display: "grid" });
  });

  it("renders the per-stage sub-label when provided", () => {
    const stages = [
      { label: "sshd accept" },
      { label: "ssh_brute_force" },
      {},
      {},
      {},
      {},
      {},
    ];
    render(<KillChain activeIdx={1} stages={stages} />);
    expect(screen.getByText("sshd accept")).toBeInTheDocument();
    expect(screen.getByText("ssh_brute_force")).toBeInTheDocument();
  });
});

describe("KillChainStageState", () => {
  it("type is exportable", () => {
    const state: KillChainStageState = "done";
    expect(state).toBe("done");
  });
});
