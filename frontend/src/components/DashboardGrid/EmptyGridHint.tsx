import { ResetLayoutButton } from "./ResetLayoutButton";

export function EmptyGridHint(): JSX.Element {
  return (
    <div className="flex h-full min-h-[320px] flex-col items-center justify-center gap-4 rounded border bg-card p-8 text-center">
      <div className="text-sm text-muted-foreground">
        Your dashboard is empty. Add a widget from the menu or reset to the default layout.
      </div>
      <ResetLayoutButton />
    </div>
  );
}
