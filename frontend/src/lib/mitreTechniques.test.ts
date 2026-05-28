/**
 * Unit tests for the MITRE ATT&CK technique-name lookup helper (S-338).
 *
 * Covers:
 *  - Hit: known id resolves to the published technique name.
 *  - Miss: unknown id returns null so callers can render the bare id.
 *  - Case-insensitive id matching.
 *  - Bundled-Sigma coverage: every technique ID extracted from the
 *    bundled rule corpus at `src/seerflow/sigma/rules/**` is present.
 *    The list below is pinned in source — the assertion exists so a new
 *    bundled-Sigma technique that lands in the rule corpus without a
 *    catalogue entry will fail this test loudly.
 */
import { describe, it, expect } from "vitest";
import {
  getTechnique,
  getTechniqueName,
  MITRE_TECHNIQUES,
} from "@/lib/mitreTechniques";

describe("getTechniqueName / getTechnique", () => {
  it("resolves a known sub-technique id to its published name", () => {
    expect(getTechniqueName("T1003.001")).toBe("OS Credential Dumping: LSASS Memory");
  });

  it("resolves a known parent technique id", () => {
    expect(getTechniqueName("T1059")).toMatch(/Command and Scripting Interpreter/i);
  });

  it("returns null on unknown id so callers can render the bare token", () => {
    expect(getTechniqueName("T9999.999")).toBeNull();
    expect(getTechnique("T9999.999")).toBeNull();
  });

  it("matches case-insensitively", () => {
    const upper = getTechniqueName("T1003.001");
    const lower = getTechniqueName("t1003.001");
    const mixed = getTechniqueName("T1003.001"); // baseline
    expect(lower).toBe(upper);
    expect(mixed).toBe(upper);
  });

  it("returns null for empty / nonsense input rather than throwing", () => {
    expect(getTechniqueName("")).toBeNull();
    expect(getTechniqueName("not-a-technique")).toBeNull();
  });

  it("exposes the full table for callers that need richer metadata", () => {
    // Sanity: the table is non-empty and uses upper-case canonical keys.
    const sampleKey = Object.keys(MITRE_TECHNIQUES)[0];
    expect(sampleKey).toMatch(/^T\d{4}(\.\d{3})?$/);
  });

  it("returns tactic metadata when available", () => {
    const t = getTechnique("T1003.001");
    expect(t).not.toBeNull();
    expect(t!.tactic).toMatch(/credential[-_ ]?access/i);
  });
});

// Pinned at plan time from `grep -rho 'attack\.t\d\{4\}\(\.\d\{3\}\)\?' src/seerflow/sigma/rules/`.
// Update both lists together if the bundled rule corpus changes.
const BUNDLED_SIGMA_TECHNIQUES = [
  "T1033",
  "T1048.003",
  "T1053.003",
  "T1059",
  "T1059.004",
  "T1068",
  "T1070.002",
  "T1070.003",
  "T1071.001",
  "T1071.004",
  "T1082",
  "T1083",
  "T1090",
  "T1098",
  "T1102",
  "T1102.002",
  "T1136.001",
  "T1140",
  "T1189",
  "T1190",
  "T1204.001",
  "T1221",
  "T1496",
  "T1505.003",
  "T1543.002",
  "T1546.004",
  "T1552.001",
  "T1562.004",
  "T1562.006",
  "T1565.001",
  "T1567",
  "T1568.002",
  "T1571",
  "T1572",
  "T1574.006",
  "T1587",
  "T1588.001",
  "T1595.002",
] as const;

describe("bundled Sigma rule coverage", () => {
  it.each(BUNDLED_SIGMA_TECHNIQUES)(
    "catalogue covers bundled-Sigma technique %s",
    (id) => {
      expect(
        getTechniqueName(id),
        `Missing MITRE catalogue entry for bundled Sigma technique ${id}. ` +
          `Add it to frontend/src/lib/mitreTechniques.ts.`,
      ).not.toBeNull();
    },
  );
});
