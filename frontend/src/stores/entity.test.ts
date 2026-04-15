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
    expect(mockedGet).toHaveBeenCalledTimes(1);
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
