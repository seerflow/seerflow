import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { RuleDetailPanel } from "./RuleDetailPanel";
import * as sigmaApi from "@/lib/sigmaRulesApi";

vi.mock("./MonacoYamlEditor", () => ({
  MonacoYamlEditor: ({ value }: { value: string }) => (
    <pre data-testid="yaml-display">{value}</pre>
  ),
}));

vi.mock("@/lib/sigmaRulesApi", () => ({
  getSigmaRule: vi.fn(),
}));

const mockedGet = sigmaApi.getSigmaRule as unknown as ReturnType<typeof vi.fn>;

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
