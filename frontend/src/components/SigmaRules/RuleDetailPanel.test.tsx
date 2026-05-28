import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  it("S-341: renders the BarHistogram hit-trend when the timeline endpoint succeeds", async () => {
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
    await waitFor(() =>
      expect(screen.getByTestId("sigma-hit-trend")).toBeInTheDocument(),
    );
    expect(screen.getByText(/^Hits · last 24h$/)).toBeInTheDocument();
  });

  it("S-341: hides the hit-trend bars silently when the timeline endpoint fails", async () => {
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
    // hit-trend container always renders; the "no timeline available" fallback
    // replaces the bars when the timeline never lands.
    await waitFor(() =>
      expect(screen.getByTestId("sigma-hit-trend")).toBeInTheDocument(),
    );
    expect(screen.getByText(/no timeline available/i)).toBeInTheDocument();
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

  it("Escape key fires onClose (S-341 — close button removed)", async () => {
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
    const panel = await screen.findByTestId("rule-detail-panel-inner");
    // S-341 mockup drops the in-panel Close button — Escape replaces it.
    expect(
      screen.queryByRole("button", { name: /close detail panel/i }),
    ).toBeNull();
    panel.focus();
    const user = userEvent.setup();
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("auto-focuses the panel on rule selection so Escape closes without a prior tab-in (S-342)", async () => {
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
    const panel = await screen.findByTestId("rule-detail-panel-inner");
    // S-342: the panel focuses itself when the rule loads — no manual
    // `panel.focus()` here (that is exactly the bug being fixed).
    await waitFor(() => expect(document.activeElement).toBe(panel));
    const user = userEvent.setup();
    await user.keyboard("{Escape}");
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

// ── S-341: mockup chrome — sticky YAML header, BarHistogram, stats row ───
describe("RuleDetailPanel — S-341 sticky YAML header (AC6)", () => {
  it("renders the sticky header with `${rule_id}.yml` and line count", async () => {
    mockedGet.mockResolvedValueOnce(
      makeRule({ rule_id: "ssh_brute_force", yaml_source: "a\nb\nc" }),
    );
    render(<RuleDetailPanel ruleId="ssh_brute_force" onClose={() => {}} />);
    const header = await screen.findByTestId("sigma-yaml-header");
    expect(header).toHaveTextContent(/ssh_brute_force\.yml/i);
    expect(header).toHaveTextContent(/3 lines/);
  });

  it("renders a Copy YAML button that calls navigator.clipboard.writeText", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    // Replace navigator.clipboard before render so the component reads our
    // spy. userEvent's own clipboard override would intercept .click(), so
    // we use fireEvent here to call the button's onClick directly.
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    mockedGet.mockResolvedValueOnce(makeRule({ yaml_source: "title: x" }));
    render(<RuleDetailPanel ruleId="r1" onClose={() => {}} />);
    await screen.findByTestId("sigma-yaml-header");
    fireEvent.click(screen.getByRole("button", { name: /^copy yaml$/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("title: x"));
  });

  it("Copy button swallows clipboard failures (no throw)", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    mockedGet.mockResolvedValueOnce(makeRule({ yaml_source: "title: x" }));
    render(<RuleDetailPanel ruleId="r1" onClose={() => {}} />);
    await screen.findByTestId("sigma-yaml-header");
    expect(() =>
      fireEvent.click(screen.getByRole("button", { name: /^copy yaml$/i })),
    ).not.toThrow();
    // Allow the rejected promise to resolve without unhandled-rejection
    // crashes — the catch handler in the component must absorb it.
    await waitFor(() => expect(writeText).toHaveBeenCalled());
  });
});

describe("RuleDetailPanel — S-341 mockup header (AC5)", () => {
  it("renders rule_id + technique badge + tactic in the inline header", async () => {
    mockedGet.mockResolvedValueOnce(
      makeRule({
        rule_id: "ssh_brute_force",
        attack_techniques: ["t1110.001"],
        attack_tactics: ["credential-access"],
      }),
    );
    render(<RuleDetailPanel ruleId="ssh_brute_force" onClose={() => {}} />);
    const header = await screen.findByTestId("rule-detail-panel-header");
    expect(header).toHaveTextContent("ssh_brute_force");
    expect(header).toHaveTextContent(/T1110\.001/);
    expect(header).toHaveTextContent("credential-access");
  });

  it("renders the 6-stat row with mockup labels", async () => {
    mockedGet.mockResolvedValueOnce(
      makeRule({
        alert_count_24h: 312,
        match_count_lifetime: 320,
        source: "seerflow",
      }),
    );
    render(<RuleDetailPanel ruleId="r1" onClose={() => {}} />);
    const stats = await screen.findByTestId("rule-detail-stats");
    expect(stats).toHaveTextContent(/hits 24h/i);
    expect(stats).toHaveTextContent(/precision/i);
    expect(stats).toHaveTextContent(/false pos/i);
    expect(stats).toHaveTextContent(/last fired/i);
    expect(stats).toHaveTextContent(/author/i);
    expect(stats).toHaveTextContent(/updated/i);
    expect(stats).toHaveTextContent("312"); // hits value
  });
});

describe("RuleDetailPanel — S-341 hit trend (AC7)", () => {
  it("renders a BarHistogram driven by timeline buckets", async () => {
    mockedGet.mockResolvedValueOnce(makeRule({ alert_count_24h: 7 }));
    mockedTimeline.mockReset();
    mockedTimeline.mockResolvedValueOnce({
      buckets: Array.from({ length: 24 }, (_, i) => ({
        bucket_start_ns: BigInt(i) * 3_600_000_000_000n,
        count: (i % 5) + 1,
      })),
    });
    render(<RuleDetailPanel ruleId="r1" onClose={() => {}} />);
    await screen.findByTestId("yaml-display");
    expect(
      await screen.findByTestId("sigma-hit-trend"),
    ).toBeInTheDocument();
    // The "Hits · last 24h" label is rendered above the histogram.
    expect(screen.getByText(/^Hits · last 24h$/)).toBeInTheDocument();
    // A peak label appears.
    expect(screen.getByTestId("sigma-hit-trend-peak")).toBeInTheDocument();
  });
});
