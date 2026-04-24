import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { SigmaRulesPage } from "./SigmaRulesPage";
import { useSigmaRulesStore } from "@/stores/sigmaRules";
import * as sigmaApi from "@/lib/sigmaRulesApi";

vi.mock("@/lib/sigmaRulesApi", () => ({
  getSigmaRules: vi.fn(),
  toggleSigmaRule: vi.fn(),
  validateSigmaRule: vi.fn(),
  uploadSigmaRule: vi.fn(),
  getSigmaRule: vi.fn(),
}));
vi.mock("./MonacoYamlEditor", () => ({
  MonacoYamlEditor: () => <div data-testid="monaco-stub" />,
}));

const mockedGet = sigmaApi.getSigmaRules as unknown as ReturnType<typeof vi.fn>;

describe("SigmaRulesPage", () => {
  beforeEach(() => {
    mockedGet.mockReset();
    useSigmaRulesStore.getState().reset();
  });

  it("loads on mount and renders rule rows", async () => {
    mockedGet.mockResolvedValueOnce({
      items: [
        {
          rule_id: "r1",
          title: "Page Test Rule",
          description: "",
          severity: 3,
          logsource_key: ["", "linux", ""],
          attack_tactics: [],
          attack_techniques: [],
          enabled: true,
          source: "bundled",
          match_count_lifetime: 0,
          last_fired_ns: null,
          alert_count_24h: 0,
        },
      ],
      total: 1,
      page: 1,
      limit: 100,
    });
    render(<SigmaRulesPage />);
    await waitFor(() => expect(screen.getByText("Page Test Rule")).toBeInTheDocument());
    expect(screen.getByText(/1 rules loaded/)).toBeInTheDocument();
  });

  it("renders error state on fetch failure", async () => {
    mockedGet.mockRejectedValueOnce(new Error("nope"));
    render(<SigmaRulesPage />);
    await waitFor(() => expect(screen.getByText(/Failed to load rules/i)).toBeInTheDocument());
  });

  it("renders empty-state when 0 rules", async () => {
    mockedGet.mockResolvedValueOnce({ items: [], total: 0, page: 1, limit: 100 });
    render(<SigmaRulesPage />);
    await waitFor(() =>
      expect(screen.getByText(/No rules match the current filters/i)).toBeInTheDocument(),
    );
  });
});
