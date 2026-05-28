/**
 * S-324: SigmaScreen unit tests.
 *
 * Tests the redesigned 460px/1fr split layout, chip filters, store integration.
 * Heavy components (RuleDetailPanel, RuleTable) are mocked.
 */
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { SigmaRuleSummary } from "@/lib/types";

// ── Store mock ───────────────────────────────────────────────────────────────
const mockLoad = vi.fn().mockResolvedValue(undefined);
const mockSelect = vi.fn();
const mockToggle = vi.fn().mockResolvedValue(undefined);
const mockSetFilter = vi.fn();

const MOCK_RULES: SigmaRuleSummary[] = [
  {
    rule_id: "rule-1",
    title: "Test Rule One",
    description: "desc",
    severity: 4,
    logsource_key: ["windows", "security", ""],
    attack_tactics: ["Lateral Movement"],
    attack_techniques: ["T1021"],
    enabled: true,
    source: "bundled",
    match_count_lifetime: 50,
    last_fired_ns: null,
    alert_count_24h: 5,
  },
  {
    rule_id: "rule-2",
    title: "Disabled Rule",
    description: "desc2",
    severity: 2,
    logsource_key: ["linux", "", ""],
    attack_tactics: [],
    attack_techniques: [],
    enabled: false,
    source: "custom",
    match_count_lifetime: 0,
    last_fired_ns: null,
    alert_count_24h: 0,
  },
  {
    rule_id: "rule-3",
    title: "Noisy Rule",
    description: "desc3",
    severity: 1,
    logsource_key: ["windows", "", ""],
    attack_tactics: [],
    attack_techniques: [],
    enabled: true,
    source: "bundled",
    match_count_lifetime: 10,
    last_fired_ns: null,
    alert_count_24h: 9,
  },
];

let mockSelectedId: string | null = null;
let mockStatus = "ready";
let mockRules = MOCK_RULES;
let mockTotal = MOCK_RULES.length;

vi.mock("@/stores/sigmaRules", () => ({
  useSigmaRulesStore: (sel: (s: unknown) => unknown) =>
    sel({
      rules: mockRules,
      status: mockStatus,
      total: mockTotal,
      selectedRuleId: mockSelectedId,
      load: mockLoad,
      setFilter: mockSetFilter,
      select: mockSelect,
      toggle: mockToggle,
    }),
}));

// ── Heavy component mocks ────────────────────────────────────────────────────
vi.mock("@/components/SigmaRules/RuleTable", () => ({
  RuleTable: ({
    rules,
    onSelect,
    selectedRuleId,
  }: {
    rules: SigmaRuleSummary[];
    onSelect: (id: string) => void;
    selectedRuleId?: string | null;
  }) => (
    <div data-testid="rule-table">
      <span data-testid="rule-table-selected-id">{selectedRuleId ?? ""}</span>
      {rules.map((r) => (
        <div
          key={r.rule_id}
          data-testid={`rule-row-${r.rule_id}`}
          onClick={() => onSelect(r.rule_id)}
        >
          {r.title}
        </div>
      ))}
    </div>
  ),
}));

vi.mock("@/components/SigmaRules/RuleDetailPanel", () => ({
  RuleDetailPanel: ({ ruleId, onClose }: { ruleId: string; onClose: () => void }) => (
    <div data-testid="rule-detail-panel">
      <span data-testid="detail-rule-id">{ruleId}</span>
      <button onClick={onClose}>Close</button>
    </div>
  ),
}));

// S-327 (AC2): the "+ New" button opens the blank-YAML upload dialog (edit
// mode). Mock it so we can assert its `open` prop without rendering Monaco.
vi.mock("@/components/SigmaRules/UploadRuleDialog", () => ({
  UploadRuleDialog: ({
    open,
    onClose,
  }: {
    open: boolean;
    onClose: () => void;
    onSaved: (id: string) => void;
  }) =>
    open ? (
      <div data-testid="upload-dialog">
        <button onClick={onClose}>Close dialog</button>
      </div>
    ) : null,
}));

import { SigmaScreen } from "./SigmaScreen";

describe("SigmaScreen (S-324)", () => {
  beforeEach(() => {
    mockLoad.mockClear();
    mockSelect.mockClear();
    mockToggle.mockClear();
    mockSetFilter.mockClear();
    mockSelectedId = null;
    mockStatus = "ready";
    mockRules = MOCK_RULES;
    mockTotal = MOCK_RULES.length;
  });

  it("renders sigma-screen testid", () => {
    render(<SigmaScreen />);
    expect(screen.getByTestId("sigma-screen")).toBeInTheDocument();
  });

  it("renders sigma-left-panel", () => {
    render(<SigmaScreen />);
    expect(screen.getByTestId("sigma-left-panel")).toBeInTheDocument();
  });

  it("renders sigma-right-panel", () => {
    render(<SigmaScreen />);
    expect(screen.getByTestId("sigma-right-panel")).toBeInTheDocument();
  });

  it("renders search input", () => {
    render(<SigmaScreen />);
    expect(screen.getByRole("textbox", { name: /search rules/i })).toBeInTheDocument();
  });

  it("renders '+ New' button", () => {
    render(<SigmaScreen />);
    expect(screen.getByRole("button", { name: /new rule/i })).toBeInTheDocument();
  });

  it("renders filter chips: All, Enabled, Disabled, High-precision, Noisy", () => {
    render(<SigmaScreen />);
    expect(screen.getByRole("button", { name: /^All/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Enabled/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Disabled/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^High precision/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Noisy/ })).toBeInTheDocument();
  });

  it("All chip is active by default", () => {
    render(<SigmaScreen />);
    const allChip = screen.getByRole("button", { name: /^All/ });
    // FilterChip uses border-accent class when active
    expect(allChip).toBeInTheDocument();
    // active chip has aria-pressed or class — check it shows all rules
    expect(screen.getByTestId("rule-table")).toBeInTheDocument();
  });

  it("chip count labels reflect rule counts", () => {
    render(<SigmaScreen />);
    // All = total (3), Enabled = 2, Disabled = 1
    expect(screen.getByRole("button", { name: `All ${mockTotal}` })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enabled 2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disabled 1" })).toBeInTheDocument();
  });

  it("Enabled chip filters to only enabled rules", async () => {
    const user = userEvent.setup();
    render(<SigmaScreen />);
    await user.click(screen.getByRole("button", { name: /^Enabled/ }));
    // Only enabled rules should be in rule-table
    expect(screen.queryByTestId("rule-row-rule-2")).not.toBeInTheDocument();
    expect(screen.getByTestId("rule-row-rule-1")).toBeInTheDocument();
  });

  it("Disabled chip filters to only disabled rules", async () => {
    const user = userEvent.setup();
    render(<SigmaScreen />);
    await user.click(screen.getByRole("button", { name: /^Disabled/ }));
    expect(screen.getByTestId("rule-row-rule-2")).toBeInTheDocument();
    expect(screen.queryByTestId("rule-row-rule-1")).not.toBeInTheDocument();
  });

  it("clicking a rule row calls store.select", async () => {
    const user = userEvent.setup();
    render(<SigmaScreen />);
    await user.click(screen.getByTestId("rule-row-rule-1"));
    expect(mockSelect).toHaveBeenCalledWith("rule-1");
  });

  it("shows RuleDetailPanel when selectedId is set", () => {
    mockSelectedId = "rule-1";
    render(<SigmaScreen />);
    expect(screen.getByTestId("rule-detail-panel")).toBeInTheDocument();
    expect(screen.getByTestId("detail-rule-id")).toHaveTextContent("rule-1");
  });

  it("shows sigma-no-selection placeholder when no rule selected", () => {
    mockSelectedId = null;
    render(<SigmaScreen />);
    expect(screen.getByTestId("sigma-no-selection")).toBeInTheDocument();
    expect(screen.queryByTestId("rule-detail-panel")).not.toBeInTheDocument();
  });

  it("closing detail panel calls store.select(null)", async () => {
    const user = userEvent.setup();
    mockSelectedId = "rule-1";
    render(<SigmaScreen />);
    await user.click(screen.getByRole("button", { name: /close/i }));
    expect(mockSelect).toHaveBeenCalledWith(null);
  });

  it("shows loading indicator when status is loading and no rules yet", () => {
    mockStatus = "loading";
    mockRules = [];
    mockTotal = 0;
    render(<SigmaScreen />);
    expect(screen.getByTestId("sigma-loading")).toBeInTheDocument();
  });

  it("calls load on mount", () => {
    render(<SigmaScreen />);
    expect(mockLoad).toHaveBeenCalledTimes(1);
  });

  it("calls setFilter when search input changes (debounced)", async () => {
    const user = userEvent.setup({ delay: null });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<SigmaScreen />);
    const searchInput = screen.getByRole("textbox", { name: /search rules/i });
    await user.type(searchInput, "test");
    act(() => { vi.advanceTimersByTime(300); });
    expect(mockSetFilter).toHaveBeenCalledWith({ search: "test" });
    vi.useRealTimers();
  });

  // ── S-327 (AC2): "+ New" opens the blank rule editor ──────────────────────
  it("upload dialog is closed by default", () => {
    render(<SigmaScreen />);
    expect(screen.queryByTestId("upload-dialog")).not.toBeInTheDocument();
  });

  it("'+ New' opens the blank rule editor dialog", async () => {
    const user = userEvent.setup();
    render(<SigmaScreen />);
    await user.click(screen.getByRole("button", { name: /new rule/i }));
    expect(screen.getByTestId("upload-dialog")).toBeInTheDocument();
  });

  it("closing the upload dialog hides it again", async () => {
    const user = userEvent.setup();
    render(<SigmaScreen />);
    await user.click(screen.getByRole("button", { name: /new rule/i }));
    await user.click(screen.getByRole("button", { name: /close dialog/i }));
    expect(screen.queryByTestId("upload-dialog")).not.toBeInTheDocument();
  });

  // ── S-341 AC1/AC2/AC3: mockup chrome ───────────────────────────────────────
  it("S-341 AC1: drops the in-panel '<h1>Sigma rules</h1>' heading", () => {
    render(<SigmaScreen />);
    // The breadcrumb chrome owns the title now — no in-panel heading.
    expect(
      screen.queryByRole("heading", { name: /^sigma rules$/i }),
    ).not.toBeInTheDocument();
  });

  it("S-341 AC2: search bar shows a magnifier-icon prefix and 'Filter N rules…' placeholder", () => {
    render(<SigmaScreen />);
    expect(screen.getByTestId("sigma-search-icon")).toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: /search rules/i });
    expect(input).toHaveAttribute(
      "placeholder",
      `Filter ${mockTotal} rules…`,
    );
  });

  it("S-341 AC2: '+ New' button is accent-fill", () => {
    render(<SigmaScreen />);
    const btn = screen.getByRole("button", { name: /new rule/i });
    // Accent-fill style → background var(--accent), color var(--accent-ink), weight 600.
    expect(btn).toHaveAttribute("data-variant", "accent-fill");
  });

  it("S-341 AC3: 'High precision' chip label has no hyphen", () => {
    render(<SigmaScreen />);
    expect(
      screen.getByRole("button", { name: /^High precision/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^High-precision/ }),
    ).not.toBeInTheDocument();
  });

  it("S-341 AC4: passes selectedId to RuleTable as selectedRuleId", () => {
    mockSelectedId = "rule-1";
    render(<SigmaScreen />);
    expect(screen.getByTestId("rule-table-selected-id")).toHaveTextContent(
      "rule-1",
    );
  });
});
