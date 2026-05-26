import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const css = fs.readFileSync(
  path.resolve(__dirname, "./globals.css"),
  "utf8",
);

describe("globals.css — OKLCH design-system tokens", () => {
  // ── Token format: OKLCH (no HSL channels) ───────────────────────────────
  it("defines OKLCH --bg on :root", () => {
    expect(css).toMatch(/:root\s*{[^}]*--bg:\s*oklch\(/s);
  });

  it("defines OKLCH --accent on :root", () => {
    expect(css).toMatch(/:root\s*{[^}]*--accent:\s*oklch\(/s);
  });

  it("defines OKLCH --warn on :root", () => {
    expect(css).toMatch(/:root\s*{[^}]*--warn:\s*oklch\(/s);
  });

  it("defines OKLCH --crit on :root", () => {
    expect(css).toMatch(/:root\s*{[^}]*--crit:\s*oklch\(/s);
  });

  it("defines --font-display on :root", () => {
    expect(css).toMatch(/:root\s*{[^}]*--font-display:/s);
  });

  // ── Light override via .sf-light (dark is default) ───────────────────────
  it("defines .sf-light light override with --bg", () => {
    expect(css).toMatch(/\.sf-light[^{]*{[^}]*--bg:/s);
  });

  it("defines .sf-light light override with --accent", () => {
    expect(css).toMatch(/\.sf-light[^{]*{[^}]*--accent:/s);
  });

  // ── Legacy [data-theme='dark'] selector is GONE ──────────────────────────
  it("does NOT contain [data-theme='dark'] selector", () => {
    expect(css).not.toMatch(/\[data-theme=['"]dark['"]\]/);
  });

  // ── shadcn compatibility bridge ──────────────────────────────────────────
  it("bridges --background to --bg", () => {
    expect(css).toMatch(/--background:\s*var\(--bg\)/);
  });

  it("bridges --foreground to --text", () => {
    expect(css).toMatch(/--foreground:\s*var\(--text\)/);
  });

  it("bridges --card to --surface", () => {
    expect(css).toMatch(/--card:\s*var\(--surface\)/);
  });

  it("bridges --primary to --accent", () => {
    expect(css).toMatch(/--primary:\s*var\(--accent\)/);
  });

  it("bridges --border to --line", () => {
    expect(css).toMatch(/--border:\s*var\(--line\)/);
  });

  it("bridges --ring to --accent", () => {
    expect(css).toMatch(/--ring:\s*var\(--accent\)/);
  });

  it("bridges --destructive to --crit", () => {
    expect(css).toMatch(/--destructive:\s*var\(--crit\)/);
  });

  it("defines --ui-accent as hover surface alias (not brand indigo)", () => {
    expect(css).toMatch(/--ui-accent:\s*var\(--surface-2\)/);
  });

  // ── Type scale utilities ─────────────────────────────────────────────────
  it("defines .sf-tnum tabular numerals", () => {
    expect(css).toMatch(/\.sf-tnum\s*{[^}]*tabular-nums/s);
  });

  it("defines .sf-mono utility", () => {
    expect(css).toMatch(/\.sf-mono\s*{[^}]*font-family:\s*var\(--font-mono\)/s);
  });
});

describe("globals.css — tailwind config validator", () => {
  const tw = fs.readFileSync(
    path.resolve(__dirname, "../../tailwind.config.ts"),
    "utf8",
  );

  it("maps accent directly to var(--accent) without hsl() wrapper", () => {
    expect(tw).toMatch(/accent['"]*:\s*['"]var\(--accent\)['"]/);
    expect(tw).not.toMatch(/hsl\(var\(--accent\)\)/);
  });

  it("maps bg directly to var(--bg)", () => {
    expect(tw).toMatch(/\bbg['"]*:\s*['"]var\(--bg\)['"]/);
  });

  it("maps line directly to var(--line)", () => {
    expect(tw).toMatch(/\bline['"]*:\s*['"]var\(--line\)['"]/);
  });

  it("maps warn directly to var(--warn)", () => {
    expect(tw).toMatch(/\bwarn['"]*:\s*['"]var\(--warn\)['"]/);
  });

  it("maps crit directly to var(--crit)", () => {
    expect(tw).toMatch(/\bcrit['"]*:\s*['"]var\(--crit\)['"]/);
  });

  it("includes ui-accent mapped to var(--surface-2)", () => {
    expect(tw).toMatch(/['"]ui-accent['"]\s*:\s*['"]var\(--surface-2\)['"]/);
  });

  it("includes display fontFamily", () => {
    expect(tw).toMatch(/display/);
  });
});
