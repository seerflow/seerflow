import { useEffect, useState } from "react";
import { Shield, BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useThemeStore } from "@/stores/theme";
import { ThemeToggle } from "@/components/brand/ThemeToggle";
import wordmarkLight from "@/assets/wordmark-light.svg";
import wordmarkDark from "@/assets/wordmark-dark.svg";
import { EntitySearch } from "@/components/EntityExplorer/EntitySearch";
import { EntityDetail } from "@/components/EntityExplorer/EntityDetail";
import { AttackHeatmap } from "@/components/AttackHeatmap/AttackHeatmap";
import { SigmaRulesPage } from "@/components/SigmaRules/SigmaRulesPage";
import { WsProvider } from "@/components/WsProvider";
import { DisconnectedBanner } from "@/components/DisconnectedBanner";
import { DashboardGrid } from "@/components/DashboardGrid/DashboardGrid";
import { AddWidgetMenu } from "@/components/DashboardGrid/AddWidgetMenu";
import { ResetLayoutButton } from "@/components/DashboardGrid/ResetLayoutButton";
import { hashHasEntity, hashHasCoverage, hashHasSigmaRules } from "@/lib/hash";
import { useEntityStore } from "@/stores/entity";
import { Toaster } from "@/components/ui/sonner";

export default function App() {
  const theme = useThemeStore((s) => s.theme);
  const toggle = useThemeStore((s) => s.toggle);
  const wordmark = theme === "dark" ? wordmarkDark : wordmarkLight;

  const [hash, setHash] = useState(() => window.location.hash);
  const restore = useEntityStore((s) => s.restoreFromHash);
  const clearSelection = useEntityStore((s) => s.clearSelection);

  useEffect(() => {
    const onHash = () => {
      const h = window.location.hash;
      setHash(h);
      if (hashHasEntity(h)) void restore(h);
      else clearSelection();
    };
    onHash();
    window.addEventListener("hashchange", onHash);
    window.addEventListener("popstate", onHash);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("popstate", onHash);
    };
  }, [restore, clearSelection]);

  const showEntity = hashHasEntity(hash);
  const showCoverage = hashHasCoverage(hash);
  const showSigmaRules = hashHasSigmaRules(hash);

  return (
    <WsProvider>
      <main className="flex flex-col min-h-screen p-6">
        <header className="mb-6 flex items-center justify-between gap-4">
          <button
            type="button"
            aria-label="Home"
            title="Home — dashboard"
            onClick={() => { window.location.hash = ""; }}
            className="cursor-pointer rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <img src={wordmark} alt="Seerflow" className="h-8 w-auto select-none" />
          </button>
          <EntitySearch />
          <AddWidgetMenu />
          <ResetLayoutButton />
          <Button variant="ghost" size="icon" aria-label="Sigma rules" title="Sigma rules — manage detection rules" onClick={() => { window.location.hash = "sigma-rules"; }}>
            <BookOpen className="h-5 w-5" />
          </Button>
          <Button variant="ghost" size="icon" aria-label="ATT&CK coverage" title="ATT&CK coverage — MITRE technique heatmap" onClick={() => { window.location.hash = "coverage"; }}>
            <Shield className="h-5 w-5" />
          </Button>
          {/* Legacy toggle (aria-label for tests); new ThemeToggle pill adds Dark/Light buttons */}
          <button
            type="button"
            aria-label="Toggle theme"
            title="Toggle theme (legacy)"
            onClick={toggle}
            style={{ display: "none" }}
          />
          <ThemeToggle />
        </header>
        <DisconnectedBanner />
        <div className="flex-1 min-h-0">
          {showEntity ? (
            <EntityDetail />
          ) : showCoverage ? (
            <AttackHeatmap />
          ) : showSigmaRules ? (
            <SigmaRulesPage />
          ) : (
            <DashboardGrid />
          )}
        </div>
      </main>
      <Toaster richColors position="bottom-right" />
    </WsProvider>
  );
}
