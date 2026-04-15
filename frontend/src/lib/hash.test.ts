import { describe, it, expect } from "vitest";
import { parseEntityHash, serializeEntityHash } from "./hash";

const UUID = "11111111-2222-3333-4444-555555555555";

describe("parseEntityHash", () => {
  it("returns null for empty hash", () => {
    expect(parseEntityHash("")).toBeNull();
    expect(parseEntityHash("#")).toBeNull();
  });
  it("parses entity uuid with default range", () => {
    expect(parseEntityHash(`#entity=${UUID}`)).toEqual({
      entity_uuid: UUID,
      range: "24h",
    });
  });
  it("parses full state", () => {
    expect(parseEntityHash(`#entity=${UUID}&range=6h&source=syslog&severity=3`)).toEqual({
      entity_uuid: UUID,
      range: "6h",
      source: "syslog",
      severity_min: 3,
    });
  });
  it("returns null on malformed UUID", () => {
    expect(parseEntityHash("#entity=not-a-uuid")).toBeNull();
  });
  it("rejects unknown keys (strict)", () => {
    expect(parseEntityHash(`#entity=${UUID}&bogus=1`)).toBeNull();
  });
  it("returns null when range is unsupported", () => {
    expect(parseEntityHash(`#entity=${UUID}&range=42y`)).toBeNull();
  });
});

describe("serializeEntityHash", () => {
  it("serializes default range only (no keys beyond entity+range)", () => {
    expect(
      serializeEntityHash({ entity_uuid: UUID, range: "24h" }),
    ).toBe(`#entity=${UUID}&range=24h`);
  });
  it("includes source and severity when present", () => {
    expect(
      serializeEntityHash({
        entity_uuid: UUID,
        range: "1h",
        source: "syslog",
        severity_min: 4,
      }),
    ).toBe(`#entity=${UUID}&range=1h&source=syslog&severity=4`);
  });
  it("round-trips", () => {
    const s = { entity_uuid: UUID, range: "7d" as const, source: "k8s", severity_min: 0 };
    expect(parseEntityHash(serializeEntityHash(s))).toEqual(s);
  });
});
