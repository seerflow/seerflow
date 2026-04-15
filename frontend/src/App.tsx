import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useThemeStore } from "@/stores/theme";
import wordmarkLight from "@/assets/wordmark-light.svg";
import wordmarkDark from "@/assets/wordmark-dark.svg";
import { AlertFeed } from "@/components/AlertFeed/AlertFeed";
import { AnomalyTimeline } from "@/components/AnomalyTimeline/AnomalyTimeline";

export default function App() {
  const theme = useThemeStore((s) => s.theme);
  const toggle = useThemeStore((s) => s.toggle);
  const Icon = theme === "dark" ? Sun : Moon;
  const wordmark = theme === "dark" ? wordmarkDark : wordmarkLight;
  return (
    <main className="min-h-screen p-6">
      <header className="mb-6 flex items-center justify-between">
        <img src={wordmark} alt="Seerflow" className="h-8 w-auto select-none" />
        <Button variant="ghost" size="icon" aria-label="Toggle theme" onClick={toggle}>
          <Icon className="h-5 w-5" />
        </Button>
      </header>
      <div className="grid gap-3 lg:grid-cols-2">
        <AlertFeed />
        <AnomalyTimeline />
      </div>
    </main>
  );
}
