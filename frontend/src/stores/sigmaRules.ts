// S-151: Sigma rules management store.
//
// Holds the rule list, filter state, currently selected rule (for the
// detail-panel deep-link), and an optimistic-toggle helper that rolls
// back if the PATCH fails.
import { create } from "zustand";
import {
  getSigmaRules,
  toggleSigmaRule,
  type ListParams,
} from "@/lib/sigmaRulesApi";
import type {
  SigmaRuleFilter,
  SigmaRuleSummary,
} from "@/lib/types";

type Status = "idle" | "loading" | "ready" | "error";

const INITIAL_FILTER: SigmaRuleFilter = {
  search: "",
  category: null,
  logsource_product: null,
  severity_in: [],
  enabledOnly: false,
  source: null,
};

export interface SigmaRulesState {
  rules: SigmaRuleSummary[];
  total: number;
  status: Status;
  selectedRuleId: string | null;
  filter: SigmaRuleFilter;
  load: () => Promise<void>;
  setFilter: (patch: Partial<SigmaRuleFilter>) => void;
  select: (ruleId: string | null) => void;
  toggle: (ruleId: string, enabled: boolean) => Promise<void>;
  reset: () => void;
}

function buildListParams(f: SigmaRuleFilter): ListParams {
  return {
    search: f.search || undefined,
    category: f.category || undefined,
    logsource_product: f.logsource_product || undefined,
    // S-154 (T8): empty array → omit query param entirely; buildQuery in
    // sigmaRulesApi already enforces this, but passing `undefined` here keeps
    // the contract obvious at the call site.
    severity_in: f.severity_in.length > 0 ? f.severity_in : undefined,
    enabled: f.enabledOnly ? true : undefined,
    source: f.source || undefined,
  };
}

export const useSigmaRulesStore = create<SigmaRulesState>((set, get) => ({
  rules: [],
  total: 0,
  status: "idle",
  selectedRuleId: null,
  filter: INITIAL_FILTER,

  load: async () => {
    set({ status: "loading" });
    try {
      const resp = await getSigmaRules(buildListParams(get().filter));
      set({ rules: resp.items, total: resp.total, status: "ready" });
    } catch {
      set({ status: "error" });
    }
  },

  setFilter: (patch) => set((s) => ({ filter: { ...s.filter, ...patch } })),

  select: (ruleId) => set({ selectedRuleId: ruleId }),

  toggle: async (ruleId, enabled) => {
    const prev = get().rules;
    set({
      rules: prev.map((r) => (r.rule_id === ruleId ? { ...r, enabled } : r)),
    });
    try {
      const updated = await toggleSigmaRule(ruleId, enabled);
      set({
        rules: get().rules.map((r) =>
          r.rule_id === ruleId ? { ...r, enabled: updated.enabled } : r,
        ),
      });
    } catch (err) {
      set({ rules: prev });
      throw err;
    }
  },

  reset: () =>
    set({
      rules: [],
      total: 0,
      status: "idle",
      selectedRuleId: null,
      filter: INITIAL_FILTER,
    }),
}));
