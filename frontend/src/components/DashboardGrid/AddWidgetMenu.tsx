import { useMemo } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { WIDGET_CATALOG } from "./WidgetCatalog";
import { useLayoutStore } from "@/stores/layout";

export function AddWidgetMenu(): JSX.Element {
  const widgets = useLayoutStore((s) => s.widgets);
  const addWidget = useLayoutStore((s) => s.addWidget);
  const mounted = useMemo(() => new Set(widgets), [widgets]);
  const notMounted = WIDGET_CATALOG.filter((w) => !mounted.has(w.id)).sort(
    (a, b) =>
      a.category === b.category
        ? a.title.localeCompare(b.title)
        : a.category === "core"
          ? -1
          : 1,
  );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" aria-label="Add widget">
          <Plus className="mr-1 h-4 w-4" /> Add widget
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {notMounted.length === 0 ? (
          <DropdownMenuLabel className="text-muted-foreground">
            All widgets on the grid
          </DropdownMenuLabel>
        ) : (
          notMounted.map((w) => (
            <DropdownMenuItem key={w.id} onSelect={() => addWidget(w.id)}>
              {w.title}
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
