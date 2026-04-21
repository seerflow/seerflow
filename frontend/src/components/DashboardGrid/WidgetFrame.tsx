import { X, GripVertical } from "lucide-react";
import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";

export function WidgetFrame({
  title,
  onRemove,
  children,
}: {
  title: string;
  onRemove: () => void;
  children: ReactNode;
}): JSX.Element {
  return (
    <Card className="flex h-full min-h-0 flex-col">
      <div className="widget-drag-handle flex cursor-move items-center justify-between border-b px-3 py-2">
        <div
          className="flex items-center gap-2 text-sm font-medium"
          role="button"
          aria-label={`Drag ${title}`}
          tabIndex={0}
          onKeyDown={(e) => {
            // Keyboard drag is a known react-grid-layout gap (documented for
            // S-062C); intercept Space here so focusing the handle and pressing
            // Space does not page-scroll the dashboard.
            if (e.key === " ") e.preventDefault();
          }}
        >
          <GripVertical className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          {title}
        </div>
        <button
          type="button"
          aria-label={`Remove ${title}`}
          className="rounded p-1 text-muted-foreground hover:bg-muted focus:outline-none focus:ring-2 focus:ring-ring"
          onClick={onRemove}
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <CardContent className="flex-1 min-h-0 overflow-hidden p-0">{children}</CardContent>
    </Card>
  );
}
