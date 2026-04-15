import { MAX_PAUSED_BUFFER } from "@/stores/events";

interface Props {
  paused: boolean;
  bufferedCount: number;
  onToggle: () => void;
}

export function PauseControl({ paused, bufferedCount, onToggle }: Props): JSX.Element {
  const atCap = bufferedCount >= MAX_PAUSED_BUFFER;
  const display = atCap ? `${MAX_PAUSED_BUFFER}+` : `${bufferedCount}`;
  return (
    <button
      type="button"
      onClick={onToggle}
      className="rounded border px-2 py-1 text-xs hover:bg-muted/60"
    >
      {paused
        ? <>▶ Resume <span className="text-muted-foreground">({display} buffered)</span></>
        : <>❚❚ Pause</>}
    </button>
  );
}
