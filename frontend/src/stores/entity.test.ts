import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useEntityStore } from "./entity";
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
