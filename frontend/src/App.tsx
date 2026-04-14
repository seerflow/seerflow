import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useThemeStore } from "@/stores/theme";

export default function App() {
  const theme = useThemeStore((s) => s.theme);
  const toggle = useThemeStore((s) => s.toggle);
  const Icon = theme === "dark" ? Sun : Moon;

  return (
    <main className="min-h-screen p-6">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Seerflow</h1>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Toggle theme"
          onClick={toggle}
        >
          <Icon className="h-5 w-5" />
        </Button>
      </header>

      <Card className="max-w-xl">
        <CardHeader>
          <CardTitle>Dashboard coming online</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Widgets land in upcoming sprint stories.
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
