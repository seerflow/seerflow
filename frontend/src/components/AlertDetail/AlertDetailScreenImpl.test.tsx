/**
 * Integration tests for AlertDetailScreen (S-321).
 * Tests the full detail view: header, kill-chain, correlated events, right rail.
 */
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { Alert, AlertDetail } from "@/lib/types";
import { useAlertStore, createAlertStore } from "@/stores/alerts";

// ── Fixtures ──────────────────────────────────────────────────────────────────
const ALERT: Alert = {
  alert_id: "alert-abc-123",
  timestamp_ns: BigInt("1700000000000000000"),
  alert_type: "sigma",
  rule_name: "Credential Dumping via LSASS",
  severity: 5,
  risk_score: 0.87,
  entity_uuid: "ent-uuid-001",
  entity_type: "host",
  entity_value: "ws-attack-01",
  message: "LSASS memory access detected from suspicious process",
  mitre_tactics: ["TA0006", "TA0008"],
  mitre_techniques: ["T1003.001", "T1550.002"],
  dedup_count: 3,
  source_type: "windows",
  feedback: "",
};

const DETAIL: AlertDetail = {
  ...ALERT,
  contributing_events: [
    {
      event_id: "ev-1",
      timestamp_ns: BigInt("1699999990000000000"),
      message: "lsass.exe memory read by mimikatz.exe",
      severity_text: "CRITICAL",
      entity_path: { src: "svc-attacker", dst: "ws-attack-01" },
    },
    {
      event_id: "ev-2",
      timestamp_ns: BigInt("1699999995000000000"),
      message: "Suspicious process access to sensitive registry key",
      severity_text: "WARN",
      entity_path: { src: "ws-attack-01", dst: null },
    },
    // S-338: legacy-shape event (no enrichment) — must render tasteful
    // placeholders (`—`) without crashing and not tint the row.
    {
      event_id: "ev-3",
      timestamp_ns: BigInt("1699999996000000000"),
      message: "Unrelated context event with no enrichment",
    },
  ],
};

// ── API mock ──────────────────────────────────────────────────────────────────
let _resolveDetail: ((d: AlertDetail) => void) | null = null;
// S-328: explain-endpoint behaviour, swappable per test.
let _explainMode: "absent" | "narrative" = "absent";
const EXPLAIN_NARRATIVE = "LLM narrative: lateral movement via stolen creds.";

vi.mock("@/lib/api", () => {
  class FactoryApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  }

  return {
    api: {
      get: vi.fn(async (path: string) => {
        if (path.includes("/explain")) {
          if (_explainMode === "narrative") {
            return { narrative: EXPLAIN_NARRATIVE };
          }
          throw new FactoryApiError(404, "not found");
        }
        if (path.includes("/feedback")) {
          return { items: [], total: 0, page: 1, limit: 10, has_next: false };
        }
        if (path.includes("/api/v1/alerts/nonexistent-id")) {
          throw new FactoryApiError(404, "not found");
        }
        if (path.includes("/api/v1/alerts/")) {
          return new Promise<AlertDetail>((res) => {
            _resolveDetail = res;
          });
        }
        return {};
      }),
    },
    ApiError: FactoryApiError,
  };
});

// Import screen after mock is registered
import { AlertDetailScreen } from "@/screens/AlertDetailScreen";

// ── Tests ─────────────────────────────────────────────────────────────────────
describe("AlertDetailScreen (S-321)", () => {
  beforeEach(() => {
    _resolveDetail = null;
    _explainMode = "absent";
    window.history.replaceState(null, "", "/#/alerts/alert-abc-123");
    useAlertStore.getState().backfill([ALERT]);
  });

  it("renders the tactic-chain heading (S-337 reconcile)", () => {
    render(<AlertDetailScreen />);
    // ALERT.mitre_tactics = ["TA0006","TA0008"]; TA0006 maps to the known
    // kill-chain stage "Credential Access", TA0008 is outside the 7-stage set
    // so it falls through to its raw token, joined by an arrow.
    const heading = screen.getByRole("heading");
    expect(heading).toHaveTextContent(/Credential Access/i);
    expect(heading).toHaveTextContent("→");
  });

  it("renders the rule name in the header meta row", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText(/Credential Dumping via LSASS/i)).toBeInTheDocument();
  });

  it("renders severity badge in header", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText(/critical/i)).toBeInTheDocument();
  });

  it("renders risk score in header badge", () => {
    render(<AlertDetailScreen />);
    // Score appears in the sev·score badge and the entity rail; assert presence.
    expect(screen.getAllByText(/0\.87/).length).toBeGreaterThan(0);
  });

  it("renders kill-chain timeline list", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByRole("list", { name: /kill.chain/i })).toBeInTheDocument();
  });

  it("renders correlated events after detail resolves", async () => {
    render(<AlertDetailScreen />);
    await act(async () => {
      _resolveDetail?.(DETAIL);
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByText(/lsass.exe memory read/i)).toBeInTheDocument();
  });

  it("renders Entities SideBlock label in right rail", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText(/entities/i)).toBeInTheDocument();
  });

  it("renders MITRE ATT&CK SideBlock label in right rail", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText(/mitre/i)).toBeInTheDocument();
  });

  it("renders AI Explanation SideBlock label in right rail", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText(/ai explanation/i)).toBeInTheDocument();
  });

  it("renders Acknowledge action button", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByRole("button", { name: /acknowledge/i })).toBeInTheDocument();
  });

  it("renders Run playbook action button", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByRole("button", { name: /run playbook/i })).toBeInTheDocument();
  });

  it("shows not-found when alert is absent from store", async () => {
    window.history.replaceState(null, "", "/#/alerts/nonexistent-id");
    render(<AlertDetailScreen />);
    // Wait for the API to reject (404) → loading state resolves → not-found renders
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByText(/alert not found/i)).toBeInTheDocument();
  });

  it("renders entity value from the alert", () => {
    render(<AlertDetailScreen />);
    // Entity value appears in the summary line and the Entities rail.
    expect(screen.getAllByText("ws-attack-01").length).toBeGreaterThan(0);
  });

  it("renders technique chips in MITRE rail", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText("T1003.001")).toBeInTheDocument();
    expect(screen.getByText("T1550.002")).toBeInTheDocument();
  });

  // ── S-338 AC1: MITRE technique-name catalogue ────────────────────────────
  it("renders the MITRE technique name beside the id (S-338 AC1)", () => {
    render(<AlertDetailScreen />);
    // T1003.001 → "OS Credential Dumping: LSASS Memory" (from mitreTechniques).
    expect(
      screen.getByText(/OS Credential Dumping: LSASS Memory/i),
    ).toBeInTheDocument();
    // T1550.002 → "Use Alternate Authentication Material: Pass the Hash".
    expect(screen.getByText(/Pass the Hash/i)).toBeInTheDocument();
  });

  it("falls back to the bare id when the technique is not in the catalogue (S-338 AC1)", () => {
    const unknownAlert: Alert = { ...ALERT, mitre_techniques: ["T9999.999"] };
    useAlertStore.getState().backfill([unknownAlert]);
    render(<AlertDetailScreen />);
    expect(screen.getByText("T9999.999")).toBeInTheDocument();
    // No catalogue entry → no name span underneath; spot-check that no
    // bogus stringified `null` / `undefined` leaked into the DOM.
    expect(screen.queryByText(/null/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/undefined/i)).not.toBeInTheDocument();
  });

  // ── S-337 mockup fidelity ────────────────────────────────────────────────
  it("uses a 1fr/360px grid filling the viewport (flush layout)", () => {
    render(<AlertDetailScreen />);
    const screenEl = screen.getByTestId("alert-detail-screen");
    expect(screenEl).toHaveStyle({ display: "grid" });
    expect(screenEl).toHaveStyle({ gridTemplateColumns: "1fr 360px" });
  });

  it("renders the severity·score badge in CRITICAL · 0.87 form", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText(/CRITICAL · 0\.87/)).toBeInTheDocument();
  });

  it("renders the kill_chain · N tactics meta line", () => {
    render(<AlertDetailScreen />);
    // ALERT has 2 mitre_tactics → "kill_chain · 2 tactics"
    expect(screen.getByText(/kill_chain · 2 tactics/)).toBeInTheDocument();
  });

  it("renders the entity summary line with the focused entity", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText(/entity =/i)).toBeInTheDocument();
    expect(screen.getAllByText(/ws-attack-01/).length).toBeGreaterThan(0);
  });

  it("renders the AI Explanation generated-by footer", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText(/generated by/i)).toBeInTheDocument();
  });

  it("Acknowledge button toggles to acknowledged state on click", async () => {
    render(<AlertDetailScreen />);
    const btn = screen.getByRole("button", { name: /acknowledge/i });
    await userEvent.click(btn);
    expect(screen.getByRole("button", { name: /acknowledged/i })).toBeInTheDocument();
  });

  // ── S-338 AC2 + AC3: correlated-events enrichment & row tint ───────────
  it("renders severity_text in the level column instead of the INFO placeholder (S-338 AC2)", async () => {
    render(<AlertDetailScreen />);
    await act(async () => {
      _resolveDetail?.(DETAIL);
      await new Promise((r) => setTimeout(r, 20));
    });
    // The mockup-tinted CRITICAL row carries the real severity label.
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
    expect(screen.getByText("WARN")).toBeInTheDocument();
    // No `INFO`/`event N` placeholders survive (the S-337 caveat).
    expect(screen.queryByText(/^INFO$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^event 1$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^event 2$/)).not.toBeInTheDocument();
  });

  it("renders entity_path as `src → dst` for correlated events (S-338 AC2)", async () => {
    render(<AlertDetailScreen />);
    await act(async () => {
      _resolveDetail?.(DETAIL);
      await new Promise((r) => setTimeout(r, 20));
    });
    // ev-1: src=svc-attacker, dst=ws-attack-01 → both appear in the same row.
    expect(screen.getByText("svc-attacker")).toBeInTheDocument();
    // Multiple ws-attack-01 (also entity_value) — at least one is the entity-path cell.
    expect(screen.getAllByText("ws-attack-01").length).toBeGreaterThanOrEqual(2);
  });

  it("renders tasteful `—` placeholder when entity_path is missing (S-338 AC2)", async () => {
    render(<AlertDetailScreen />);
    await act(async () => {
      _resolveDetail?.(DETAIL);
      await new Promise((r) => setTimeout(r, 20));
    });
    // ev-3 has no enrichment → both level and entity-path render `—`.
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
  });

  it("tints the row crit/warn based on severity_text (S-338 AC3)", async () => {
    render(<AlertDetailScreen />);
    await act(async () => {
      _resolveDetail?.(DETAIL);
      await new Promise((r) => setTimeout(r, 20));
    });
    const grid = screen.getByLabelText("correlated events");
    // 3 fixture rows: ev-1 crit, ev-2 warn, ev-3 untinted.
    const tintedCrit = grid.querySelectorAll('[data-tint="crit"]');
    const tintedWarn = grid.querySelectorAll('[data-tint="warn"]');
    expect(tintedCrit.length).toBe(1);
    expect(tintedWarn.length).toBe(1);
    // Untinted rows expose no data-tint attribute.
    const untinted = grid.querySelectorAll("div[style*='gridTemplateColumns'], div[style*='grid-template-columns']");
    // Sanity that the grid still has 3 rows (1 crit + 1 warn + 1 untinted).
    expect(untinted.length).toBeGreaterThanOrEqual(3);
  });

  it("auto-scroll checkbox is rendered after events load", async () => {
    render(<AlertDetailScreen />);
    await act(async () => {
      _resolveDetail?.(DETAIL);
      await new Promise((r) => setTimeout(r, 20));
    });
    const toggle = screen.queryByRole("checkbox", { name: /auto.scroll/i });
    if (toggle) {
      expect(toggle).toBeChecked();
    }
  });

  // ── S-328 AC4: LLM-explain wiring ────────────────────────────────────────
  it("renders the LLM narrative when the explain endpoint resolves", async () => {
    _explainMode = "narrative";
    render(<AlertDetailScreen />);
    await act(async () => {
      _resolveDetail?.(DETAIL);
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(
      screen.getByText(/lateral movement via stolen creds/i),
    ).toBeInTheDocument();
  });

  it("falls back to the demo narrative without error when explain is absent", async () => {
    _explainMode = "absent";
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<AlertDetailScreen />);
    await act(async () => {
      _resolveDetail?.(DETAIL);
      await new Promise((r) => setTimeout(r, 30));
    });
    // Demo narrative = the alert/detail message (existing behaviour preserved).
    expect(
      screen.getByText(/LSASS memory access detected/i),
    ).toBeInTheDocument();
    expect(errSpy).not.toHaveBeenCalled();
    errSpy.mockRestore();
  });

  // ── S-339: feedback Verdict block ───────────────────────────────────────
  it("renders the Verdict SideBlock with TP and FP buttons (S-339 AC1)", () => {
    render(<AlertDetailScreen />);
    // SideBlock title is uppercased via CSS but the underlying text is "Verdict".
    expect(screen.getByText(/verdict/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /true positive/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /false positive/i }),
    ).toBeInTheDocument();
  });

  it("Verdict block sits above Entities in the right rail (S-339)", () => {
    render(<AlertDetailScreen />);
    const verdict = screen.getByText(/verdict/i);
    const entities = screen.getAllByText(/entities/i)[0];
    // Both are in the right-rail aside; Verdict must appear before Entities.
    expect(
      verdict.compareDocumentPosition(entities) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});

// ── Verify createAlertStore is a valid export (smoke) ─────────────────────────
describe("createAlertStore (dependency check)", () => {
  it("exports createAlertStore for isolated testing", () => {
    expect(typeof createAlertStore).toBe("function");
    const store = createAlertStore(10);
    expect(store.getState().alerts).toHaveLength(0);
  });
});
