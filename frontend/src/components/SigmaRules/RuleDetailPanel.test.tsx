import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { RuleDetailPanel } from "./RuleDetailPanel";
import * as sigmaApi from "@/lib/sigmaRulesApi";

// S-327: the Monaco mock now exposes `readOnly`, `value`, and `onChange` so
// the Edit-YAML toggle (AC3) can be asserted without rendering real Monaco.
vi.mock("./MonacoYamlEditor", () => ({
  MonacoYamlEditor: ({
    value,
    readOnly,
    onChange,
  }: {
    value: string;
    readOnly?: boolean;
    onChange?: (v: string) => void;
  }) => (
    <textarea
      data-testid="yaml-display"
      data-readonly={readOnly ? "true" : "false"}
      readOnly={!!readOnly}
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}));

vi.mock("@/lib/sigmaRulesApi", () => ({
  getSigmaRule: vi.fn(),
  getSigmaRuleTimeline: vi.fn(),
  toggleSigmaRule: vi.fn(),
}));

const mockedGet = sigmaApi.getSigmaRule as unknown as ReturnType<typeof vi.fn>;
const mockedTimeline = sigmaApi.getSigmaRuleTimeline as unknown as ReturnType<
  typeof vi.fn
>;
const mockedToggle = sigmaApi.toggleSigmaRule as unknown as ReturnType<
  typeof vi.fn
>;

beforeEach(() => {
  mockedGet.mockReset();
  mockedTimeline.mockReset();
  mockedToggle.mockReset();
  // Default: timeline rejects so existing tests behave as before.
  mockedTimeline.mockRejectedValue(new Error("no timeline by default"));
});

describe("RuleDetailPanel", () => {
  it("renders YAML, severity, and ATT&CK technique link with target=_blank", async () => {
    mockedGet.mockResolvedValueOnce({
      rule_id: "r1",
      title: "Test",
      description: "d",
      severity: 3,
      logsource_key: ["", "linux", ""],
      attack_tactics: [],
      attack_techniques: ["t1059.001"],
      enabled: true,
      source: "bundled",
      yaml_source: "title: Test",
      match_count_lifetime: 0,
      last_fired_ns: null,
      alert_count_24h: 0,
    });
    render(<RuleDetailPanel ruleId="r1" onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByTestId("yaml-display")).toHaveValue("title: Test"),
    );
    const link = screen.getByRole("link", { name: /T1059\.001/i });
    expect(link.getAttribute("href")).toBe(
      "https://attack.mitre.org/techniques/T1059/001/",
    );
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.getAttribute("target")).toBe("_blank");
  });

  it("shows error message on fetch failure", async () => {
    mockedGet.mockRejectedValueOnce(new Error("nope"));
    render(<RuleDetailPanel ruleId="r1" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/failed to load rule/i)).toBeInTheDocument());
  });

  it("renders the 24h sparkline when the timeline endpoint succeeds", async () => {
    mockedGet.mockResolvedValueOnce({
      rule_id: "r1",
      title: "T",
      description: "",
      severity: 3,
      logsource_key: ["", "linux", ""],
      attack_tactics: [],
      attack_techniques: [],
      enabled: true,
      source: "bundled",
      yaml_source: "",
      match_count_lifetime: 0,
      last_fired_ns: null,
      alert_count_24h: 7,
    });
    mockedTimeline.mockReset();
    mockedTimeline.mockResolvedValueOnce({
      buckets: Array.from({ length: 24 }, (_, i) => ({
        bucket_start_ns: BigInt(i) * 3_600_000_000_000n,
        count: i % 4,
      })),
    });
    render(<RuleDetailPanel ruleId="r1" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("rule-sparkline")).toBeInTheDocument());
    expect(document.querySelector("polyline")).not.toBeNull();
  });

  it("hides the sparkline silently when the timeline endpoint fails", async () => {
    mockedGet.mockResolvedValueOnce({
      rule_id: "r1",
      title: "T",
      description: "",
      severity: 3,
      logsource_key: ["", "linux", ""],
      attack_tactics: [],
      attack_techniques: [],
      enabled: true,
      source: "bundled",
      yaml_source: "",
      match_count_lifetime: 0,
      last_fired_ns: null,
      alert_count_24h: 0,
    });
    // mockedTimeline already rejects via the default in beforeEach.
    render(<RuleDetailPanel ruleId="r1" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/24h alerts/i)).toBeInTheDocument());
    expect(screen.queryByTestId("rule-sparkline")).toBeNull();
  });

  it("aborts in-flight fetches when ruleId changes (S-230)", async () => {
    const detailSignals: AbortSignal[] = [];
    const timelineSignals: AbortSignal[] = [];
    mockedGet.mockReset();
    mockedGet.mockImplementation((id: string, signal?: AbortSignal) => {
      if (signal) detailSignals.push(signal);
      return new Promise((resolve) => {
        setTimeout(
          () =>
            resolve({
              rule_id: id,
              title: id,
              description: "",
              severity: 3,
              logsource_key: ["", "linux", ""],
              attack_tactics: [],
              attack_techniques: [],
              enabled: true,
              source: "bundled",
              yaml_source: "",
              match_count_lifetime: 0,
              last_fired_ns: null,
              alert_count_24h: 0,
            }),
          50,
        );
      });
    });
    mockedTimeline.mockReset();
    mockedTimeline.mockImplementation(
      (_id: string, signal?: AbortSignal) => {
        if (signal) timelineSignals.push(signal);
        return Promise.reject(new Error("no timeline"));
      },
    );

    const { rerender } = render(
      <RuleDetailPanel ruleId="r1" onClose={() => {}} />,
    );
    await waitFor(() => expect(detailSignals.length).toBe(1));
    rerender(<RuleDetailPanel ruleId="r2" onClose={() => {}} />);
    await waitFor(() => expect(detailSignals.length).toBe(2));

    expect(detailSignals[0].aborted).toBe(true);
    expect(timelineSignals[0]).toBe(detailSignals[0]);
    expect(detailSignals[1].aborted).toBe(false);
    // The abort of r1 must not surface an error banner.
    expect(screen.queryByText(/failed to load rule/i)).toBeNull();
  });

  it("close button fires onClose", async () => {
    mockedGet.mockResolvedValueOnce({
      rule_id: "r1",
      title: "T",
      description: "",
      severity: 3,
      logsource_key: ["", "linux", ""],
      attack_tactics: [],
      attack_techniques: [],
      enabled: true,
      source: "bundled",
      yaml_source: "",
      match_count_lifetime: 0,
      last_fired_ns: null,
      alert_count_24h: 0,
    });
    const onClose = vi.fn();
    render(<RuleDetailPanel ruleId="r1" onClose={onClose} />);
    const btn = await screen.findByRole("button", { name: /close detail panel/i });
    btn.click();
    expect(onClose).toHaveBeenCalled();
  });
});

// ── S-327: Edit YAML (AC3) + Test on history (AC4) ──────────────────────────
function makeRule(overrides: Record<string, unknown> = {}) {
  return {
    rule_id: "r1",
    title: "Editable Rule",
    description: "",
    severity: 3,
    logsource_key: ["", "linux", ""],
    attack_tactics: [],
    attack_techniques: [],
    enabled: true,
    source: "bundled",
    yaml_source: "title: Editable Rule",
    match_count_lifetime: 42,
    last_fired_ns: null,
    alert_count_24h: 0,
    ...overrides,
  };
}

describe("RuleDetailPanel — Edit YAML (S-327 AC3)", () => {
  it("renders the editor read-only by default", async () => {
    mockedGet.mockResolvedValueOnce(makeRule());
    render(<RuleDetailPanel ruleId="r1" onClose={() => {}} />);
    const editor = await screen.findByTestId("yaml-display");
    expect(editor).toHaveAttribute("data-readonly", "true");
  });

  it("Edit YAML toggles the editor into editable mode", async () => {
    const user = userEvent.setup();
    mockedGet.mockResolvedValueOnce(makeRule());
    render(<RuleDetailPanel ruleId="r1" onClose={() => {}} />);
    await screen.findByTestId("yaml-display");
    await user.click(screen.getByRole("button", { name: /^edit yaml$/i }));
    expect(screen.getByTestId("yaml-display")).toHaveAttribute(
      "data-readonly",
      "false",
    );
  });

  it("edits flow into a local draft while editing", async () => {
    const user = userEvent.setup();
    mockedGet.mockResolvedValueOnce(makeRule({ yaml_source: "a" }));
    render(<RuleDetailPanel ruleId="r1" onClose={() => {}} />);
    await screen.findByTestId("yaml-display");
    await user.click(screen.getByRole("button", { name: /^edit yaml$/i }));
    const editor = screen.getByTestId("yaml-display");
    await user.type(editor, "b");
    expect(editor).toHaveValue("ab");
  });

  it("Cancel reverts to read-only with the original YAML", async () => {
    const user = userEvent.setup();
    mockedGet.mockResolvedValueOnce(makeRule({ yaml_source: "orig" }));
    render(<RuleDetailPanel ruleId="r1" onClose={() => {}} />);
    await screen.findByTestId("yaml-display");
    await user.click(screen.getByRole("button", { name: /^edit yaml$/i }));
    const editor = screen.getByTestId("yaml-display");
    await user.type(editor, "X");
    expect(editor).toHaveValue("origX");
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));
    const reverted = screen.getByTestId("yaml-display");
    expect(reverted).toHaveAttribute("data-readonly", "true");
    expect(reverted).toHaveValue("orig");
  });
});

describe("RuleDetailPanel — Test on history (S-327 AC4)", () => {
  it("surfaces 24h hit count from the loaded timeline + lifetime matches", async () => {
    const user = userEvent.setup();
    mockedGet.mockResolvedValueOnce(makeRule({ match_count_lifetime: 42 }));
    mockedTimeline.mockReset();
    mockedTimeline.mockResolvedValueOnce({
      buckets: [
        { bucket_start_ns: 0n, count: 2 },
        { bucket_start_ns: 3_600_000_000_000n, count: 3 },
        { bucket_start_ns: 7_200_000_000_000n, count: 0 },
      ],
    });
    render(<RuleDetailPanel ruleId="r1" onClose={() => {}} />);
    await screen.findByTestId("yaml-display");
    await user.click(screen.getByRole("button", { name: /^test on history$/i }));
    const result = await screen.findByTestId("sigma-test-result");
    // 2 + 3 + 0 = 5 hits in the 24h window.
    expect(result).toHaveTextContent("5");
    // lifetime matches surfaced too.
    expect(result).toHaveTextContent("42");
  });

  it("falls back gracefully when no timeline history is available", async () => {
    const user = userEvent.setup();
    mockedGet.mockResolvedValueOnce(makeRule({ match_count_lifetime: 7 }));
    // timeline rejects via the default beforeEach mock → no buckets loaded.
    render(<RuleDetailPanel ruleId="r1" onClose={() => {}} />);
    await screen.findByTestId("yaml-display");
    await user.click(screen.getByRole("button", { name: /^test on history$/i }));
    const result = await screen.findByTestId("sigma-test-result");
    expect(result).toHaveTextContent(/no recent history/i);
    expect(result).toHaveTextContent("7");
  });
});
