/**
 * S-346 — Dark-mode / brand-token sweep guard.
 *
 * Walks `frontend/src/**` and asserts that no source file (re-)introduces the
 * Tailwind palette utility classes or hex literals that the brand-token sweep
 * targets. The forbidden patterns are exactly the ones listed in AC1 of
 * `docs/stories/S-346.md`:
 *
 *   - `bg-zinc-<N>` / `text-zinc-<N>` / `border-zinc-<N>` (any palette step)
 *   - `bg-white` / `bg-black` / `text-white` / `text-black` (incl. `/<opacity>`)
 *   - inline / style-prop hardcoded `#xxxxxx` colour literals
 *
 * S-349 extends the same guard to the bright SEMANTIC palette families that
 * S-346 deferred — `red` / `orange` / `amber` / `yellow` / `green` / `emerald` /
 * `lime` / `teal` palette steps. These must use the brand semantic tokens
 * (`crit`/`warn`/`info`/`destructive`) so the hues flip per theme.
 *
 * Intentional, narrowly-justified exceptions are kept on an allowlist below.
 * Each entry pairs a path glob with the regex it is allowed to match — adding a
 * raw "ignore everything" rule for a whole file is deliberately not supported,
 * so future regressions in the same file still surface.
 *
 * If you need to add a new exception, document the reason inline in the
 * allowlist AND add a `// design-token-sweep S-346: intentional — <reason>`
 * annotation in the source file (AC3 of S-346).
 */
import { describe, it, expect } from "vitest";
import { promises as fs } from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC_ROOT = HERE; // tests live alongside src; HERE === <repo>/frontend/src

const ZINC_RE = /\b(?:bg|text|border|hover:bg|hover:text|divide)-zinc-\d+/;
const BW_RE = /\b(?:bg|text)-(?:white|black)(?:\/\d+)?\b/;
const HEX_RE = /#[0-9a-fA-F]{3,8}\b/;
// S-349 — bright semantic Tailwind palette literals that the semantic-palette
// sweep replaced with the brand tokens (`crit`/`warn`/`info`/`destructive`).
// Once migrated, re-introducing any of these hue families as a fixed palette
// step (red / orange / amber / yellow / green / emerald / lime / teal) is a
// regression: those literals have no `.sf-light` variant and read muddy in the
// theme they were not tuned for. Migrate to the brand semantic tokens instead.
const SEMANTIC_RE =
  /\b(?:bg|text|border|hover:bg|hover:text|divide)-(?:red|orange|amber|yellow|green|emerald|lime|teal)-\d+/;

interface AllowlistEntry {
  /** Glob-free path suffix the file path must end with (POSIX separators). */
  pathSuffix: string;
  /** Regex the line must match for the exception to apply. */
  pattern: RegExp;
  /** Human reason — surfaces in failure messages, mostly documentation. */
  reason: string;
}

const ALLOWLIST: AllowlistEntry[] = [
  // S-343/S-344 — Monaco-safe fallback hex; story explicitly excludes
  // `monacoTheme.ts` FALLBACKS from the sweep.
  {
    pathSuffix: "components/SigmaRules/monacoTheme.ts",
    pattern: HEX_RE,
    reason: "S-343/S-344 Monaco-safe FALLBACKS — intentional hex per story AC.",
  },
  {
    pathSuffix: "components/SigmaRules/monacoTheme.test.ts",
    pattern: HEX_RE,
    reason: "Mirrors FALLBACKS hex; asserts the table structure.",
  },
  // shadcn modal scrim — `bg-black/80` is the conventional dim layer behind a
  // dialog/sheet and reads correctly in both themes.
  {
    pathSuffix: "components/ui/alert-dialog.tsx",
    pattern: /bg-black\/80/,
    reason: "Radix dialog overlay scrim — intentional modal dim layer.",
  },
  {
    pathSuffix: "components/ui/sheet.tsx",
    pattern: /bg-black\/80/,
    reason: "Radix sheet overlay scrim — intentional modal dim layer.",
  },
  // S-345 historical comment inside `TechniqueCell.tsx` references the removed
  // `bg-white dark:bg-zinc-900` classes as part of the explanation. The
  // component itself is already migrated to brand tokens.
  {
    pathSuffix: "components/AttackHeatmap/TechniqueCell.tsx",
    pattern: /bg-white dark:bg-zinc-900/,
    reason: "S-345 explanatory comment — documents the removed classes.",
  },
  // S-346 — same kind of historical comment inside `DrilldownPanel.tsx`'s
  // `AlertRow` doc block explaining what `hover:bg-zinc-50 dark:hover:bg-zinc-900/40`
  // was replaced with. The component itself is migrated to brand tokens.
  {
    pathSuffix: "components/AttackHeatmap/DrilldownPanel.tsx",
    pattern: /hover:bg-zinc-50 dark:hover:bg-zinc-900\/40/,
    reason: "S-346 explanatory comment — documents the removed classes.",
  },
  // Note (S-349): the `low` severity band intentionally keeps the neutral
  // `slate-500` grey (theme-stable muted neutral). `slate` is deliberately NOT
  // in SEMANTIC_RE's hue list, so no allowlist entry is needed — the kept
  // decision is documented inline in `lib/severity.ts` and pinned by
  // `severity.test.ts`. critical/high/medium migrated to `crit`/`warn` tokens.
  //
  // Test files: the S-345/S-346/S-349 regression tests intentionally include the
  // forbidden tokens in their assertion regexes (asserting absence). Filtered
  // by the test-file extension below.
];

async function walk(dir: string, out: string[] = []): Promise<string[]> {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  for (const e of entries) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) {
      // Skip nothing — every directory under src/ is in scope.
      await walk(full, out);
    } else if (e.isFile()) {
      if (e.name.endsWith(".ts") || e.name.endsWith(".tsx")) {
        out.push(full);
      }
    }
  }
  return out;
}

function isAllowed(file: string, line: string): boolean {
  // A line is allowed iff at least one ALLOWLIST entry both matches the file
  // path AND its `pattern` matches the line. The active rule that flagged the
  // line is irrelevant — the allowlist is line-pattern-anchored, so a
  // `bg-zinc-200` introduced in `monacoTheme.ts` (whose allowlist pattern is
  // the hex regex) would NOT be allowed: the hex regex won't match
  // `bg-zinc-200`.
  const posix = file.split(path.sep).join("/");
  for (const entry of ALLOWLIST) {
    if (!posix.endsWith(entry.pathSuffix)) continue;
    if (entry.pattern.test(line)) return true;
  }
  return false;
}

interface Violation {
  file: string;
  line: number;
  text: string;
  rule: string;
}

async function scan(): Promise<Violation[]> {
  const files = await walk(SRC_ROOT);
  const out: Violation[] = [];
  const rules: Array<{ name: string; re: RegExp }> = [
    { name: "zinc-palette", re: ZINC_RE },
    { name: "bw-palette", re: BW_RE },
    { name: "hex-literal", re: HEX_RE },
    { name: "semantic-palette", re: SEMANTIC_RE },
  ];
  for (const file of files) {
    // Skip test files entirely for the bw/zinc rules — they may legitimately
    // assert the patterns are absent via regex matches. The hex rule still
    // applies because we want guards to not regress on fixture-hex sneaking in.
    const isTest = /\.(test|spec)\.(ts|tsx)$/.test(file);
    // Skip this guard file itself (it contains the regexes by definition).
    if (file === fileURLToPath(import.meta.url)) continue;
    const content = await fs.readFile(file, "utf8");
    const lines = content.split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      for (const rule of rules) {
        if (isTest && rule.name !== "hex-literal") continue;
        if (!rule.re.test(line)) continue;
        if (isAllowed(file, line)) continue;
        out.push({
          file: path.relative(SRC_ROOT, file),
          line: i + 1,
          text: line.trim(),
          rule: rule.name,
        });
      }
    }
  }
  return out;
}

describe("design-token sweep guard (S-346 / S-349)", () => {
  it("does not introduce forbidden Tailwind palette classes or hex literals", async () => {
    const violations = await scan();
    if (violations.length > 0) {
      const lines = violations.map(
        (v) => `  ${v.file}:${v.line}  [${v.rule}]  ${v.text}`,
      );
      throw new Error(
        `${violations.length} forbidden colour usage(s) under frontend/src/:\n` +
          lines.join("\n") +
          "\n\nMigrate to brand CSS tokens (var(--surface) / var(--text-3), or the " +
          "crit/warn/info/destructive Tailwind tokens) or add a justified allowlist " +
          "entry in design-tokens.guard.test.ts.",
      );
    }
    expect(violations).toEqual([]);
  });

  // S-349 — assert the new semantic-palette rule actually catches the bright
  // hue families it is meant to guard, so AC4 ("no new un-annotated violations
  // slip past the guard") is itself verified rather than assumed.
  it("semantic-palette rule flags each bright hue family it guards", () => {
    for (const cls of [
      "text-red-500",
      "bg-orange-500/15",
      "text-amber-700",
      "bg-yellow-500/15",
      "bg-green-500/10",
      "bg-emerald-100",
    ]) {
      expect(SEMANTIC_RE.test(cls)).toBe(true);
    }
    // The kept neutral slate band and the brand tokens must NOT be flagged.
    for (const cls of ["text-slate-500", "text-crit", "bg-warn/10", "text-info", "bg-destructive/10"]) {
      expect(SEMANTIC_RE.test(cls)).toBe(false);
    }
  });
});
