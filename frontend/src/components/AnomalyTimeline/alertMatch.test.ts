import { describe, it, expect } from "vitest";
import { findAlertInBucket } from "./alertMatch";

describe("findAlertInBucket bigint precision (S-194)", () => {
  it("matches a bigint alert timestamp inside a high-ns bucket window without precision loss", () => {
    const bucketStartNs = 1_700_000_000_000_000_000;
    const resolutionNs = 60_000_000_000;
    const alerts = [{ timestamp_ns: 1_700_000_000_000_000_123n, alert_id: "a1" }];
    expect(findAlertInBucket(alerts, bucketStartNs, resolutionNs)?.alert_id).toBe("a1");
  });

  it("does not match a timestamp outside the bucket window", () => {
    const bucketStartNs = 1_700_000_000_000_000_000;
    const resolutionNs = 60_000_000_000;
    const alerts = [{ timestamp_ns: 1_700_000_060_000_000_000n, alert_id: "a2" }];
    expect(findAlertInBucket(alerts, bucketStartNs, resolutionNs)).toBeUndefined();
  });

  it("matches a number timestamp inside the bucket window", () => {
    const bucketStartNs = 1_000_000;
    const resolutionNs = 500_000;
    const alerts = [{ timestamp_ns: 1_200_000, alert_id: "a3" }];
    expect(findAlertInBucket(alerts, bucketStartNs, resolutionNs)?.alert_id).toBe("a3");
  });

  it("returns undefined for an empty alert list", () => {
    expect(findAlertInBucket([], 1_000_000, 500_000)).toBeUndefined();
  });
});
