// S-151: Top-level Sigma rules management page.
//
// Composes FilterBar + RuleTable + RuleDetailPanel + UploadRuleDialog
// against `useSigmaRulesStore`. Loads on mount; refetches when the filter
// changes; surfaces toast feedback for toggle / upload outcomes.
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { useSigmaRulesStore } from "@/stores/sigmaRules";
import { Button } from "@/components/ui/button";

import { FilterBar } from "./FilterBar";
import { RuleDetailPanel } from "./RuleDetailPanel";
import { RuleTable } from "./RuleTable";
import { UploadRuleDialog } from "./UploadRuleDialog";

export function SigmaRulesPage(): JSX.Element {
  const rules = useSigmaRulesStore((s) => s.rules);
  const status = useSigmaRulesStore((s) => s.status);
  const total = useSigmaRulesStore((s) => s.total);
  const selectedRuleId = useSigmaRulesStore((s) => s.selectedRuleId);
  const filter = useSigmaRulesStore((s) => s.filter);

  const [uploadOpen, setUploadOpen] = useState(false);

  useEffect(() => {
    void useSigmaRulesStore.getState().load();
    // Re-load whenever any filter field changes.
  }, [filter]);

  return (
    <section className="flex flex-1 min-h-0">
      <div className="flex flex-col min-w-0 flex-1 border-r">
        <header className="flex items-center justify-between border-b px-4 py-3">
          <div>
            <h1 className="text-lg font-semibold">Sigma rules</h1>
            <p className="text-xs text-muted-foreground">
              {status === "ready" ? `${total} rules loaded` : "Loading…"}
            </p>
          </div>
          <Button size="sm" onClick={() => setUploadOpen(true)}>
            Upload rule
          </Button>
        </header>

        <FilterBar
          initialSearch={filter.search}
          onChange={(patch) => useSigmaRulesStore.getState().setFilter(patch)}
        />

        {status === "loading" && (
          <div className="px-4 py-6 text-sm text-muted-foreground">Loading…</div>
        )}
        {status === "error" && (
          <div className="px-4 py-6 text-sm text-destructive">
            Failed to load rules.
          </div>
        )}
        {status === "ready" && (
          <div className="overflow-y-auto flex-1">
            <RuleTable
              rules={rules}
              onSelect={(id) => useSigmaRulesStore.getState().select(id)}
              onToggle={(id, enabled) => {
                useSigmaRulesStore
                  .getState()
                  .toggle(id, enabled)
                  .catch(() => toast.error("Failed to update rule"));
              }}
            />
          </div>
        )}
      </div>

      {selectedRuleId && (
        <RuleDetailPanel
          ruleId={selectedRuleId}
          onClose={() => useSigmaRulesStore.getState().select(null)}
        />
      )}

      <UploadRuleDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onSaved={() => {
          toast.success("Rule uploaded");
          void useSigmaRulesStore.getState().load();
        }}
      />
    </section>
  );
}
