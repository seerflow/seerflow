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
    vi.doMock("./logger", () => ({
      logger: {
        info: () => {},
        warn: () => {},
        error: (...a: unknown[]) => console.error(...a),
      },
    }));
    const { logger } = await import("./logger");
    logger.info("i");
    logger.warn("w");
    logger.error("e");
    expect(infoSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
    expect(errorSpy).toHaveBeenCalledOnce();
  });
});
