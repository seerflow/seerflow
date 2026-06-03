import React from "react";
import { cn } from "@/lib/utils";

export type KbdHintProps = React.HTMLAttributes<HTMLElement>;

/**
 * Hairline-boxed keyboard shortcut hint — `<kbd>` in Geist Mono.
 * Example: <KbdHint>⌘K</KbdHint>
 */
export const KbdHint: React.FC<KbdHintProps> = ({ className, children, ...props }) => (
  <kbd
    className={cn(
      "sf-mono inline-flex items-center border border-line px-[4px] py-[1px] text-[10.5px] text-text-3",
      className,
    )}
    {...props}
  >
    {children}
  </kbd>
);
