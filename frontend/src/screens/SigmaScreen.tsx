/**
 * S-324: Sigma rules screen — 460px / 1fr split layout.
 *
 * Left panel: search + "+ New" + FilterChip row + RuleTable.
 * Right panel: RuleDetailPanel when rule selected, placeholder otherwise.
 *
 * Client-side chip filtering (All/Enabled/Disabled/High-precision/Noisy)
 * is applied on top of the store's rule list. The store handles server-side
 * text search via setFilter({ search }) with debounce.
 */
import React, { useState, useEffect, useMemo, useRef } from "react";
import { useSigmaRulesStore } from "@/stores/sigmaRules";
import type { SigmaRuleSummary } from "@/lib/types";
import { FilterChip, FilterRow } from "@/components/ui/primitives/FilterChip";
import { RuleTable } from "@/components/SigmaRules/RuleTable";
import { RuleDetailPanel } from "@/components/SigmaRules/RuleDetailPanel";

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
      return `High-precision ${rules.filter((r) => r.match_count_lifetime >= 10 && r.alert_count_24h > 0).length}`;
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
        style={{ display: "flex", flexDirection: "column", overflow: "hidden", borderRight: "1px solid var(--line)" }}
      >
        {/* Search + New */}
        <div className="flex items-center gap-2 p-3 border-b border-line">
          <input
            aria-label="Search rules"
            placeholder="Search rules…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 bg-transparent sf-mono text-sm text-text placeholder:text-text-3 outline-none"
          />
          <button
            className="sf-mono text-xs text-accent border border-[color-mix(in_oklch,var(--accent)_35%,transparent)] px-2 py-1 leading-none whitespace-nowrap hover:bg-[color-mix(in_oklch,var(--accent)_8%,transparent)] transition-colors"
            aria-label="New rule"
          >
            + New
          </button>
        </div>

        {/* Filter chips */}
        <div className="p-2 border-b border-line">
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
    </div>
  );
};
