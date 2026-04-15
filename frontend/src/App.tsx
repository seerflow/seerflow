import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useThemeStore } from "@/stores/theme";
import wordmarkLight from "@/assets/wordmark-light.svg";
import wordmarkDark from "@/assets/wordmark-dark.svg";
import { AlertFeed } from "@/components/AlertFeed/AlertFeed";
import { AnomalyTimeline } from "@/components/AnomalyTimeline/AnomalyTimeline";
import { EntitySearch } from "@/components/EntityExplorer/EntitySearch";
import { EntityDetail } from "@/components/EntityExplorer/EntityDetail";
import { EventStream } from "@/components/EventStream/EventStream";
import { hashHasEntity } from "@/lib/hash";
import { useEntityStore } from "@/stores/entity";

export default function App() {
  const theme = useThemeStore((s) => s.theme);
  const toggle = useThemeStore((s) => s.toggle);
  const Icon = theme === "dark" ? Sun : Moon;
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

  return (
    <main className="min-h-screen p-6">
      <header className="mb-6 flex items-center justify-between gap-4">
        <img src={wordmark} alt="Seerflow" className="h-8 w-auto select-none" />
        <EntitySearch />
        <Button variant="ghost" size="icon" aria-label="Toggle theme" onClick={toggle}>
          <Icon className="h-5 w-5" />
        </Button>
      </header>
      {showEntity ? (
        <EntityDetail />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          <AlertFeed />
          <AnomalyTimeline />
          <div className="lg:col-span-2"><EventStream /></div>
        </div>
      )}
    </main>
  );
}
