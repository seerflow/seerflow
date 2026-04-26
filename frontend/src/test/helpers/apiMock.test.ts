import { describe, it, expect, vi, beforeEach } from "vitest";
import * as v from "valibot";
import { applySchemaValidation, createApiMock, DefaultMockApiError } from "./apiMock";
import { _resetForTests as resetMetrics, getCounters } from "@/lib/validationMetrics";

const ItemSchema = v.object({ id: v.string(), n: v.number() });
const RootSchema = v.object({ ok: v.boolean() });

describe("applySchemaValidation", () => {
  beforeEach(() => resetMetrics());

  it("passes through when no schema", () => {
    const body = { foo: "bar" };
    expect(applySchemaValidation(body, "/x", undefined)).toBe(body);
    expect(applySchemaValidation(body, "/x", {})).toBe(body);
  });

  it("per-row branch drops invalid rows and increments rest:<path> counter", () => {
    const body = { items: [{ id: "a", n: 1 }, { id: "b", n: "bad" }, { id: "c", n: 2 }] };
    const out = applySchemaValidation(body, "/api/v1/items?page=1", { schema: ItemSchema, itemsKey: "items" }) as { items: unknown[] };
    expect(out.items).toEqual([{ id: "a", n: 1 }, { id: "c", n: 2 }]);
    expect(getCounters()["rest:/api/v1/items"]).toBe(1);
  });

  it("per-row branch throws when body[itemsKey] is not an array", () => {
    expect(() => applySchemaValidation({ items: "nope" }, "/x", { schema: ItemSchema, itemsKey: "items" }))
      .toThrowError(/response-schema-fail: expected array at "items"/);
  });

  it("per-row branch throws when body has no itemsKey field", () => {
    expect(() => applySchemaValidation({}, "/x", { schema: ItemSchema, itemsKey: "items" }))
      .toThrowError(/response-schema-fail: expected array at "items"/);
  });

  it("scalar-schema branch returns parsed output on success", () => {
    expect(applySchemaValidation({ ok: true }, "/x", { schema: RootSchema })).toEqual({ ok: true });
  });

  it("scalar-schema branch throws on schema mismatch with joined messages", () => {
    expect(() => applySchemaValidation({ ok: "yes" }, "/x", { schema: RootSchema }))
      .toThrowError(/response-schema-fail:/);
  });

  it("uses the supplied ErrorClass when provided", () => {
    class MyErr extends Error { status = 999; constructor(_s: number, m: string) { super(m); } }
    expect(() => applySchemaValidation({ items: 0 }, "/x", { schema: ItemSchema, itemsKey: "items" }, MyErr as never))
      .toThrow(MyErr);
  });
});

describe("createApiMock", () => {
  it("api.get uses fetchMock when provided and applies schema validation", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ items: [{ id: "a", n: 1 }, { id: "b", n: "x" }] });
    const { api } = createApiMock({ fetchMock });
    const out = await api.get("/api/v1/items", { schema: ItemSchema, itemsKey: "items" });
    expect(fetchMock).toHaveBeenCalledWith("GET", "/api/v1/items", { schema: ItemSchema, itemsKey: "items" });
    expect((out as { items: unknown[] }).items).toEqual([{ id: "a", n: 1 }]);
  });

  it("api.get returns defaultGetResponse when no fetchMock", async () => {
    const { api } = createApiMock({ defaultGetResponse: { items: [], total: 0 } });
    const out = await api.get("/api/v1/anything");
    expect(out).toEqual({ items: [], total: 0 });
  });

  it("api.post defaults to vi.fn and accepts override", async () => {
    const def = createApiMock();
    expect(typeof def.api.post).toBe("function");
    const override = vi.fn().mockReturnValue("ok");
    const withOverride = createApiMock({ postImpl: override });
    expect(withOverride.api.post("/x", { y: 1 })).toBe("ok");
    expect(override).toHaveBeenCalledTimes(1);
    expect(override).toHaveBeenCalledWith("/x", { y: 1 });
  });

  it("exports DefaultMockApiError with status/detail/debugDetail/cause props", () => {
    const e = new DefaultMockApiError(0, "msg", "debug-info", { foo: 1 });
    expect(e.status).toBe(0);
    expect(e.message).toBe("msg");
    expect(e.debugDetail).toBe("debug-info");
    expect(e.cause).toEqual({ foo: 1 });
    expect(e.name).toBe("ApiError");
  });
});
