import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("logger DEV gate (S-194 AC-4)", () => {
  let infoSpy: ReturnType<typeof vi.spyOn>;
  let warnSpy: ReturnType<typeof vi.spyOn>;
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    infoSpy = vi.spyOn(console, "info").mockImplementation(() => {});
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("emits info/warn/error in DEV", async () => {
    const { logger } = await import("./logger");
    logger.info("i");
    logger.warn("w");
    logger.error("e");
    expect(infoSpy).toHaveBeenCalledOnce();
    expect(warnSpy).toHaveBeenCalledOnce();
    expect(errorSpy).toHaveBeenCalledOnce();
  });

  it("no-ops info/warn but emits error in production", async () => {
    // import.meta.env.DEV is a compile-time literal in Vitest 2.x; vi.stubEnv
    // cannot flip it (DEV stays true even when MODE=production).  Instead,
    // logger.ts initialises globalThis.__DEV__ from import.meta.env.DEV on
    // first load, so tests can override it via vi.stubGlobal before the module
    // is re-evaluated under a fresh module registry.
    vi.stubGlobal("__DEV__", false);
    vi.resetModules();
    const { logger } = await import("./logger");
    logger.info("i");
    logger.warn("w");
    logger.error("e");
    expect(infoSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
    expect(errorSpy).toHaveBeenCalledOnce();
  });
});
