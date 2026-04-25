import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useEntityStore, currentViewState } from "./entity";
import { api } from "@/lib/api";

const UUID = "11111111-2222-3333-4444-555555555555";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn() },
  ApiError: class extends Error { constructor(public status: number, msg: string) { super(msg); } },
}));

const mockedGet = api.get as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockedGet.mockReset();
  useEntityStore.setState(useEntityStore.getInitialState());
  localStorage.clear();
});

afterEach(() => { vi.useRealTimers(); });

describe("entityStore.runSearch", () => {
  it("debounces and fetches /entities/search", async () => {
    mockedGet.mockResolvedValue([
      { entity_type: "user", entity_value: "alice", entity_uuid: UUID },
    ]);
    useEntityStore.getState().setQuery("alice");
    await useEntityStore.getState().runSearch();
    expect(mockedGet).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/entities/search?q=alice"),
      expect.any(Object),
    );
    expect(useEntityStore.getState().searchResults).toHaveLength(1);
  });
  it("aborts in-flight fetches on re-trigger", async () => {
    const abortSpy = vi.fn();
    mockedGet.mockImplementation((_path, opts) => {
      opts?.signal?.addEventListener("abort", abortSpy);
      return new Promise(() => {});
    });
    useEntityStore.getState().setQuery("a");
    void useEntityStore.getState().runSearch();
    useEntityStore.getState().setQuery("al");
    void useEntityStore.getState().runSearch();
    expect(abortSpy).toHaveBeenCalled();
  });
});

describe("entityStore.selectEntity + refresh", () => {
  it("selectEntity triggers timeline fetch", async () => {
    mockedGet.mockResolvedValueOnce({
      entity_uuid: UUID,
      events: [],
      related: [],
      total: 0,
    });
    await useEntityStore.getState().selectEntity(UUID);
    expect(useEntityStore.getState().selectedEntityUuid).toBe(UUID);
    expect(mockedGet).toHaveBeenCalledWith(
      expect.stringContaining(`/api/v1/entities/${UUID}/timeline`),
      expect.any(Object),
    );
  });
  it("setRange refetches with new window", async () => {
    mockedGet.mockResolvedValue({ entity_uuid: UUID, events: [], related: [], total: 0 });
    await useEntityStore.getState().selectEntity(UUID);
    mockedGet.mockClear();
    await useEntityStore.getState().setRange("6h");
    // S-060.F1: setRange now refetches both timeline and risk-history.
    const timelineCalls = mockedGet.mock.calls.filter((c) =>
      String(c[0]).includes("/timeline"),
    );
    expect(timelineCalls).toHaveLength(1);
  });
});

describe("entityStore.pushRecent + clearRecent", () => {
  const r = { entity_type: "user", entity_value: "a", entity_uuid: UUID };
  it("persists recent to localStorage (max 10, dedup by uuid)", () => {
    useEntityStore.getState().pushRecent(r);
    useEntityStore.getState().pushRecent(r);
    expect(useEntityStore.getState().recent).toHaveLength(1);
    const stored = JSON.parse(localStorage.getItem("seerflow:recentEntities")!);
    expect(stored).toHaveLength(1);
  });
  it("clearRecent empties both memory and storage", () => {
    useEntityStore.getState().pushRecent(r);
    useEntityStore.getState().clearRecent();
    expect(useEntityStore.getState().recent).toHaveLength(0);
    expect(localStorage.getItem("seerflow:recentEntities")).toBeNull();
  });
});

describe("loadRecent validates localStorage entries", () => {
  it("drops tampered / malformed entries at module load", async () => {
    localStorage.setItem(
      "seerflow:recentEntities",
      JSON.stringify([
        { entity_type: "user", entity_value: "ok", entity_uuid: UUID },
        { entity_type: "user", entity_value: "bad", entity_uuid: "../../evil" },
        { entity_uuid: UUID }, // missing fields
        "not-an-object",
        null,
      ]),
    );
    vi.resetModules();
    const { useEntityStore: fresh } = await import("./entity");
    const recent = fresh.getState().recent;
    expect(recent).toHaveLength(1);
    expect(recent[0]?.entity_uuid).toBe(UUID);
  });
});

describe("entityStore.restoreFromHash", () => {
  it("applies hash state and triggers fetch", async () => {
    mockedGet.mockResolvedValue({ entity_uuid: UUID, events: [], related: [], total: 0 });
    await useEntityStore.getState().restoreFromHash(`#entity=${UUID}&range=1h`);
    expect(useEntityStore.getState().selectedEntityUuid).toBe(UUID);
    expect(useEntityStore.getState().range).toBe("1h");
  });
  it("ignores malformed hashes", async () => {
    await useEntityStore.getState().restoreFromHash(`#entity=bogus`);
    expect(useEntityStore.getState().selectedEntityUuid).toBeNull();
  });
});

describe("entityStore error and filter paths", () => {
  it("runSearch with empty query clears results without fetch", async () => {
    useEntityStore.getState().setQuery("   ");
    await useEntityStore.getState().runSearch();
    expect(useEntityStore.getState().searchResults).toEqual([]);
    expect(mockedGet).not.toHaveBeenCalled();
  });

  it("runSearch surfaces error message on failure", async () => {
    mockedGet.mockRejectedValueOnce(new Error("network down"));
    useEntityStore.getState().setQuery("alice");
    await useEntityStore.getState().runSearch();
    expect(useEntityStore.getState().error).toBe("network down");
    expect(useEntityStore.getState().loading).toBe("error");
  });

  it("runSearch surfaces 429 throttle message", async () => {
    const ApiErrorMod = (await import("@/lib/api")).ApiError;
    mockedGet.mockRejectedValueOnce(new ApiErrorMod(429, "rate limited"));
    useEntityStore.getState().setQuery("alice");
    await useEntityStore.getState().runSearch();
    expect(useEntityStore.getState().error).toMatch(/throttled/i);
  });

  it("refresh surfaces error on timeline failure", async () => {
    mockedGet.mockRejectedValueOnce(new Error("boom"));
    useEntityStore.setState({ selectedEntityUuid: UUID });
    await useEntityStore.getState().refresh();
    expect(useEntityStore.getState().loading).toBe("error");
    expect(useEntityStore.getState().error).toBe("boom");
  });

  it("refresh is a no-op when no entity selected", async () => {
    await useEntityStore.getState().refresh();
    expect(mockedGet).not.toHaveBeenCalled();
  });

  it("setSourceFilter triggers refresh when entity selected", async () => {
    mockedGet.mockResolvedValue({ entity_uuid: UUID, events: [], related: [], total: 0 });
    await useEntityStore.getState().selectEntity(UUID);
    mockedGet.mockClear();
    await useEntityStore.getState().setSourceFilter("syslog");
    expect(mockedGet).toHaveBeenCalledTimes(1);
    expect(mockedGet.mock.calls[0][0]).toContain("source_type=syslog");
  });

  it("setSeverityMin triggers refresh when entity selected", async () => {
    mockedGet.mockResolvedValue({ entity_uuid: UUID, events: [], related: [], total: 0 });
    await useEntityStore.getState().selectEntity(UUID);
    mockedGet.mockClear();
    await useEntityStore.getState().setSeverityMin(4);
    expect(mockedGet).toHaveBeenCalledTimes(1);
    expect(mockedGet.mock.calls[0][0]).toContain("severity_min=4");
  });

  it("setRange / setSourceFilter / setSeverityMin do NOT fetch if no entity selected", async () => {
    await useEntityStore.getState().setRange("1h");
    await useEntityStore.getState().setSourceFilter("syslog");
    await useEntityStore.getState().setSeverityMin(2);
    expect(mockedGet).not.toHaveBeenCalled();
  });

  it("clearSelection wipes events/related/total/filters", () => {
    useEntityStore.setState({
      selectedEntityUuid: UUID,
      events: [{ event_id: "x" } as never],
      related: [{ entity_uuid: "y" } as never],
      total: 5,
      sourceFilter: "syslog",
      severityMin: 3,
    });
    useEntityStore.getState().clearSelection();
    expect(useEntityStore.getState().selectedEntityUuid).toBeNull();
    expect(useEntityStore.getState().events).toEqual([]);
    expect(useEntityStore.getState().related).toEqual([]);
    expect(useEntityStore.getState().total).toBe(0);
    expect(useEntityStore.getState().sourceFilter).toBeNull();
    expect(useEntityStore.getState().severityMin).toBeNull();
  });

  it("currentViewState returns null when no selection, full state otherwise", () => {
    expect(currentViewState()).toBeNull();
    useEntityStore.setState({
      selectedEntityUuid: UUID,
      range: "6h",
      sourceFilter: "syslog",
      severityMin: 2,
    });
    expect(currentViewState()).toEqual({
      entity_uuid: UUID,
      range: "6h",
      source: "syslog",
      severity_min: 2,
    });
  });

  it("persistRecent guards against full localStorage", () => {
    const orig = Storage.prototype.setItem;
    Storage.prototype.setItem = () => { throw new Error("QuotaExceeded"); };
    try {
      // Should not throw
      useEntityStore.getState().pushRecent({
        entity_type: "user", entity_value: "carol", entity_uuid: UUID,
      });
      expect(useEntityStore.getState().recent).toHaveLength(1);
    } finally {
      Storage.prototype.setItem = orig;
    }
  });
});

describe("entityStore.fetchRiskHistory (S-060.F1)", () => {
  beforeEach(() => {
    useEntityStore.getState().clearSelection();
  });

  it("populates riskHistory on success", async () => {
    mockedGet.mockResolvedValueOnce({
      meta: { range: "1h", resolution: "1m", alert_count_truncated: false },
      items: [
        { bucket_start_ns: "0", points: 1.2, alert_count: 2, top_rule_name: "r" },
      ],
    });
    useEntityStore.setState({
      selectedEntityUuid: "11111111-1111-1111-1111-111111111111",
      range: "1h",
    });
    await useEntityStore.getState().fetchRiskHistory();
    const s = useEntityStore.getState();
    expect(s.riskHistory).toHaveLength(1);
    expect(s.riskHistoryLoading).toBe(false);
    expect(s.riskHistoryError).toBeNull();
    expect(mockedGet).toHaveBeenCalledWith(
      expect.stringContaining(
        "/api/v1/entities/11111111-1111-1111-1111-111111111111/risk-history?range=1h",
      ),
      expect.any(Object),
    );
  });

  it("no-ops when no entity is selected", async () => {
    useEntityStore.setState({ selectedEntityUuid: null });
    await useEntityStore.getState().fetchRiskHistory();
    expect(mockedGet).not.toHaveBeenCalled();
  });

  it("sets error state on fetch failure", async () => {
    mockedGet.mockRejectedValueOnce(new Error("boom"));
    useEntityStore.setState({
      selectedEntityUuid: "22222222-2222-2222-2222-222222222222",
      range: "1h",
    });
    await useEntityStore.getState().fetchRiskHistory();
    const s = useEntityStore.getState();
    expect(s.riskHistoryError).not.toBeNull();
    expect(s.riskHistoryLoading).toBe(false);
  });

  it("clearSelection resets riskHistory to []", () => {
    useEntityStore.setState({
      riskHistory: [
        { bucket_start_ns: "0", points: 1, alert_count: 1, top_rule_name: "r" },
      ],
    });
    useEntityStore.getState().clearSelection();
    expect(useEntityStore.getState().riskHistory).toEqual([]);
  });
});

describe("entityStore.discoveredSourceTypes (S-060.F2)", () => {
  const ev = (id: string, source_type: string) => ({
    event_id: id,
    timestamp_ns: 1n,
    source_type,
    severity_id: 3,
    message: "m",
    entity_refs: [],
  });

  it("seeds discoveredSourceTypes from refresh() response (sorted union)", async () => {
    mockedGet.mockResolvedValueOnce({
      entity_uuid: UUID,
      events: [ev("e1", "syslog"), ev("e2", "auth"), ev("e3", "syslog")],
      related: [],
      total: 3,
    });
    useEntityStore.setState({ selectedEntityUuid: UUID });
    await useEntityStore.getState().refresh();
    expect(useEntityStore.getState().discoveredSourceTypes).toEqual(["auth", "syslog"]);
  });

  it("unions discoveredSourceTypes across successive refresh() calls (narrowing-safe)", async () => {
    mockedGet
      .mockResolvedValueOnce({
        entity_uuid: UUID,
        events: [ev("e1", "syslog"), ev("e2", "auth")],
        related: [],
        total: 2,
      })
      .mockResolvedValueOnce({
        entity_uuid: UUID,
        events: [ev("e3", "k8s")],
        related: [],
        total: 1,
      });
    useEntityStore.setState({ selectedEntityUuid: UUID });
    await useEntityStore.getState().refresh();
    await useEntityStore.getState().refresh();
    expect(useEntityStore.getState().discoveredSourceTypes).toEqual(["auth", "k8s", "syslog"]);
  });
});

describe("entityStore.selectEntity filter reset (S-060.F2)", () => {
  it("resets sourceFilter, severityMin, discoveredSourceTypes before refresh()", async () => {
    mockedGet.mockResolvedValueOnce({
      entity_uuid: UUID,
      events: [],
      related: [],
      total: 0,
    });
    useEntityStore.setState({
      sourceFilter: "syslog",
      severityMin: 3,
      discoveredSourceTypes: ["syslog", "auth"],
      selectedEntityUuid: UUID,
    });
    const NEW_UUID = "22222222-2222-2222-2222-222222222222";
    await useEntityStore.getState().selectEntity(NEW_UUID);
    const s = useEntityStore.getState();
    expect(s.sourceFilter).toBeNull();
    expect(s.severityMin).toBeNull();
    expect(s.discoveredSourceTypes).toEqual([]);
  });

  it("preserves the active range across selectEntity", async () => {
    mockedGet.mockResolvedValueOnce({
      entity_uuid: UUID,
      events: [],
      related: [],
      total: 0,
    });
    useEntityStore.setState({ range: "7d" });
    await useEntityStore.getState().selectEntity(UUID);
    expect(useEntityStore.getState().range).toBe("7d");
  });
});

describe("entityStore.clearSelection clears discoveredSourceTypes (S-060.F2)", () => {
  it("clears discoveredSourceTypes alongside other entity state", () => {
    useEntityStore.setState({
      selectedEntityUuid: UUID,
      discoveredSourceTypes: ["syslog", "auth"],
    });
    useEntityStore.getState().clearSelection();
    expect(useEntityStore.getState().discoveredSourceTypes).toEqual([]);
  });
});

describe("entityStore.restoreFromHash does NOT reset filter keys (S-060.F2)", () => {
  it("applies source/severity from hash without zero-ing them", async () => {
    mockedGet.mockResolvedValueOnce({
      entity_uuid: UUID,
      events: [],
      related: [],
      total: 0,
    });
    await useEntityStore
      .getState()
      .restoreFromHash(`#entity=${UUID}&range=24h&source=syslog&severity=3`);
    const s = useEntityStore.getState();
    expect(s.sourceFilter).toBe("syslog");
    expect(s.severityMin).toBe(3);
  });
});

describe("entityStore.restoreFromHash discoveredSourceTypes cache reset (S-060.F2)", () => {
  const UUID_B = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

  it("clears discoveredSourceTypes when crossing entity boundaries", async () => {
    useEntityStore.setState({
      selectedEntityUuid: UUID,
      discoveredSourceTypes: ["syslog", "auth"],
    });
    mockedGet.mockResolvedValueOnce({
      entity_uuid: UUID_B,
      events: [{ source_type: "k8s" } as never],
      related: [],
      total: 1,
    });
    await useEntityStore
      .getState()
      .restoreFromHash(`#entity=${UUID_B}&range=24h`);
    const s = useEntityStore.getState();
    expect(s.selectedEntityUuid).toBe(UUID_B);
    expect(s.discoveredSourceTypes).toEqual(["k8s"]);
  });

  it("preserves discoveredSourceTypes for same-entity hash restore (e.g. range chip change)", async () => {
    useEntityStore.setState({
      selectedEntityUuid: UUID,
      discoveredSourceTypes: ["auth", "syslog"],
    });
    mockedGet.mockResolvedValueOnce({
      entity_uuid: UUID,
      events: [{ source_type: "syslog" } as never],
      related: [],
      total: 1,
    });
    await useEntityStore
      .getState()
      .restoreFromHash(`#entity=${UUID}&range=1h`);
    const s = useEntityStore.getState();
    expect(s.discoveredSourceTypes).toEqual(["auth", "syslog"]);
  });
});
