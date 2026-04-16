import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeLogger } from "./logger";

describe("makeLogger DEV gate (S-194 AC-4)", () => {
  let infoSpy: ReturnType<typeof vi.spyOn>;
  let warnSpy: ReturnType<typeof vi.spyOn>;
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    infoSpy = vi.spyOn(console, "info").mockImplementation(() => {});
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("emits info/warn/error in DEV", () => {
    const logger = makeLogger(true);
    logger.info("i"); logger.warn("w"); logger.error("e");
    expect(infoSpy).toHaveBeenCalledOnce();
    expect(warnSpy).toHaveBeenCalledOnce();
    expect(errorSpy).toHaveBeenCalledOnce();
  });

  it("no-ops info/warn but emits error in production", () => {
    const logger = makeLogger(false);
    logger.info("i"); logger.warn("w"); logger.error("e");
    expect(infoSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
    expect(errorSpy).toHaveBeenCalledOnce();
  });
});
