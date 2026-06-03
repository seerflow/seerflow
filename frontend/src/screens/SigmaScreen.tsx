/**
 * S-324 / S-341: Sigma rules screen — 460px / 1fr split layout.
 *
 * S-341 reconciles the chrome to `docs/new_image/Dashboard - Sigma Rules.html`:
 *   - drops the in-panel `<h1>` (AC1)
 *   - search bar wrapped in a `var(--surface)` box with a magnifier-icon
 *     prefix and placeholder `Filter N rules…` (AC2)
 *   - `+ New` button is accent-fill (AC2)
 *   - chip label tweak `High-precision` → `High precision` (AC3)
 *   - selected rule highlight is now driven by `selectedRuleId` propagation
 *     into `RuleTable` (AC4)
 *
 * S-327 functional bits preserved: debounced server-side search, client-side
 * chip filter, `+ New` opens the blank-rule editor (UploadRuleDialog).
 */
import React, { useState, useEffect, useMemo, useRef } from "react";
import { useSigmaRulesStore } from "@/stores/sigmaRules";
import type { SigmaRuleSummary } from "@/lib/types";
import { FilterChip, FilterRow } from "@/components/ui/primitives/FilterChip";
import { RuleTable } from "@/components/SigmaRules/RuleTable";
import { RuleDetailPanel } from "@/components/SigmaRules/RuleDetailPanel";
import { UploadRuleDialog } from "@/components/SigmaRules/UploadRuleDialog";

type ChipId = "all" | "enabled" | "disabled" | "high-precision" | "noisy";

const CHIP_ORDER: ChipId[] = ["all", "enabled", "disabled", "high-precision", "noisy"];

function applyChipFilter(rules: SigmaRuleSummary[], chip: ChipId): SigmaRuleSummary[] {
  switch (chip) {
    case "all":
      return rules;
    case "enabled":
      return rules.filter((r) => r.enabled);
    case "disabled":
      return rules.filter((r) => !r.enabled);
    case "high-precision":
      // Proxy: rules with lifetime matches ≥ 10 and recent activity.
      return rules.filter((r) => r.match_count_lifetime >= 10 && r.alert_count_24h > 0);
    case "noisy":
      // Proxy: rules where 24h alerts > 50% of lifetime matches (many false positives).
      return rules.filter(
        (r) => r.match_count_lifetime > 0 && r.alert_count_24h / r.match_count_lifetime > 0.5,
      );
  }
}

function chipLabel(chip: ChipId, rules: SigmaRuleSummary[], total: number): string {
  switch (chip) {
    case "all":
      return `All ${total}`;
    case "enabled":
      return `Enabled ${rules.filter((r) => r.enabled).length}`;
    case "disabled":
      return `Disabled ${rules.filter((r) => !r.enabled).length}`;
    case "high-precision":
      // S-341 AC3: label has no hyphen ("High precision").
      return `High precision ${rules.filter((r) => r.match_count_lifetime >= 10 && r.alert_count_24h > 0).length}`;
    case "noisy":
      return `Noisy ${rules.filter((r) => r.match_count_lifetime > 0 && r.alert_count_24h / r.match_count_lifetime > 0.5).length}`;
  }
}

const DEBOUNCE_MS = 250;

export const SigmaScreen: React.FC = () => {
  const rules = useSigmaRulesStore((s) => s.rules);
  const status = useSigmaRulesStore((s) => s.status);
  const total = useSigmaRulesStore((s) => s.total);
  const selectedId = useSigmaRulesStore((s) => s.selectedRuleId);
  const load = useSigmaRulesStore((s) => s.load);
  const setFilter = useSigmaRulesStore((s) => s.setFilter);
  const select = useSigmaRulesStore((s) => s.select);
  const toggle = useSigmaRulesStore((s) => s.toggle);

  const [chip, setChip] = useState<ChipId>("all");
  const [search, setSearch] = useState("");
  // S-327 (AC2): "+ New" opens the blank-YAML rule editor (UploadRuleDialog).
  const [newOpen, setNewOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Initial load with abort on unmount.
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  // Debounced server-side search.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setFilter({ search });
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [search, setFilter]);

  // Client-side chip filter applied on top of store rules.
  const filteredRules = useMemo(() => applyChipFilter(rules, chip), [rules, chip]);

  const chipLabels = useMemo(
    () =>
      Object.fromEntries(
        CHIP_ORDER.map((c) => [c, chipLabel(c, rules, total)]),
      ) as Record<ChipId, string>,
    [rules, total],
  );

  return (
    <div
      data-testid="sigma-screen"
      style={{
        display: "grid",
        gridTemplateColumns: "460px 1fr",
        height: "100%",
        overflow: "hidden",
      }}
    >
      {/* Left panel */}
      <div
        data-testid="sigma-left-panel"
        style={{
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          borderRight: "1px solid var(--line)",
        }}
      >
        {/* S-341 AC2: Search + accent-fill "+ New" — no in-panel heading. */}
        <div
          style={{
            padding: "14px 18px",
            borderBottom: "1px solid var(--line)",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              flex: 1,
              background: "var(--surface)",
              border: "1px solid var(--line)",
              padding: "5px 10px",
            }}
          >
            <svg
              data-testid="sigma-search-icon"
              width="11"
              height="11"
              viewBox="0 0 14 14"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.4"
              style={{ color: "var(--text-3)" }}
              aria-hidden="true"
            >
              <circle cx="6" cy="6" r="4.5" />
              <path d="M10 10l3 3" />
            </svg>
            <input
              aria-label="Search rules"
              placeholder={`Filter ${total} rules…`}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="flex-1 bg-transparent sf-mono text-sm text-text placeholder:text-text-3 outline-none"
              style={{ background: "transparent", border: 0, width: "100%" }}
            />
          </div>
          <button
            onClick={() => setNewOpen(true)}
            data-variant="accent-fill"
            aria-label="New rule"
            style={{
              background: "var(--accent)",
              border: 0,
              color: "var(--accent-ink)",
              padding: "5px 10px",
              fontSize: 11.5,
              fontWeight: 600,
              fontFamily: "inherit",
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            + New
          </button>
        </div>

        {/* Filter chips */}
        <div
          style={{
            padding: "10px 18px",
            borderBottom: "1px solid var(--line)",
          }}
        >
          <FilterRow>
            {CHIP_ORDER.map((c) => (
              <FilterChip
                key={c}
                label={chipLabels[c]}
                active={chip === c}
                onClick={() => setChip(c)}
              />
            ))}
          </FilterRow>
        </div>

        {/* Rule table */}
        <div style={{ flex: 1, overflow: "auto" }}>
          {status === "loading" && rules.length === 0 ? (
            <div
              data-testid="sigma-loading"
              className="p-4 text-sm text-text-3 sf-mono"
            >
              Loading…
            </div>
          ) : (
            <RuleTable
              rules={filteredRules}
              selectedRuleId={selectedId}
              onSelect={(id) => select(id)}
              onToggle={(id, enabled) => void toggle(id, enabled)}
            />
          )}
        </div>
      </div>

      {/* Right panel */}
      <div
        data-testid="sigma-right-panel"
        style={{ overflow: "hidden", height: "100%" }}
      >
        {selectedId ? (
          <RuleDetailPanel ruleId={selectedId} onClose={() => select(null)} />
        ) : (
          <div
            data-testid="sigma-no-selection"
            className="flex h-full items-center justify-center text-sm text-text-3 sf-mono"
          >
            Select a rule to view details
          </div>
        )}
      </div>

      {/* S-327 (AC2): blank-rule editor — opens on "+ New". After a save the
          list reloads and the freshly-created rule is auto-selected. */}
      <UploadRuleDialog
        open={newOpen}
        onClose={() => setNewOpen(false)}
        onSaved={(ruleId) => {
          void load();
          select(ruleId);
          setNewOpen(false);
        }}
      />
    </div>
  );
};
