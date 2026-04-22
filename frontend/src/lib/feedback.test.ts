import { describe, expect, it, vi, beforeEach } from "vitest";
import { submitFeedback } from "@/lib/feedback";
import { useAlertStore } from "@/stores/alerts";
import { toast } from "sonner";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe("submitFeedback", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    useAlertStore.setState({
      alerts: [
        {
          alert_id: "a-1",
          timestamp_ns: 1n,
          alert_type: "ml",
          rule_name: "r",
          severity: 10,
          risk_score: 0.1,
          entity_uuid: null,
          entity_type: null,
          entity_value: null,
          message: "",
          mitre_tactics: [],
          mitre_techniques: [],
          dedup_count: 1,
          feedback: undefined,
        },
      ] as unknown as ReturnType<typeof useAlertStore.getState>["alerts"],
      feedbackVersion: {},
    });
    vi.clearAllMocks();
    fetchMock.mockReset();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  it("optimistically updates, POSTs dashboard origin, bumps version on success", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    await submitFeedback("a-1", "tp");
    const s = useAlertStore.getState();
    expect(s.alerts[0].feedback).toBe("tp");
    expect(s.feedbackVersion["a-1"]).toBe(1);
    expect(toast.success).toHaveBeenCalledWith("Marked as true positive", { duration: 3000 });
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ feedback: "tp", origin: "dashboard" });
  });

  it("rolls back and toasts error on failure", async () => {
    fetchMock.mockResolvedValue(
      new Response('{"detail":"err"}', {
        status: 500,
        headers: { "content-type": "application/json" },
      }),
    );
    await submitFeedback("a-1", "fp");
    expect(useAlertStore.getState().alerts[0].feedback).toBeFalsy();
    expect(toast.error).toHaveBeenCalledWith(expect.any(String), { duration: 5000 });
  });
});
