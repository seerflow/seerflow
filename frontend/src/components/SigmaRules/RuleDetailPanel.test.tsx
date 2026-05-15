import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { RuleDetailPanel } from "./RuleDetailPanel";
import * as sigmaApi from "@/lib/sigmaRulesApi";

vi.mock("./MonacoYamlEditor", () => ({
  MonacoYamlEditor: ({ value }: { value: string }) => (
    <pre data-testid="yaml-display">{value}</pre>
  ),
}));

vi.mock("@/lib/sigmaRulesApi", () => ({
  getSigmaRule: vi.fn(),
  getSigmaRuleTimeline: vi.fn(),
}));

const mockedGet = sigmaApi.getSigmaRule as unknown as ReturnType<typeof vi.fn>;
const mockedTimeline = sigmaApi.getSigmaRuleTimeline as unknown as ReturnType<
  typeof vi.fn
>;

beforeEach(() => {
  mockedGet.mockReset();
  mockedTimeline.mockReset();
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
      expect(screen.getByTestId("yaml-display")).toHaveTextContent("title: Test"),
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
