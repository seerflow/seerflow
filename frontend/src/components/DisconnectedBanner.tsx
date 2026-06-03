import { useEffect, useState } from "react";
import * as wsBus from "@/lib/wsBus";
import type { WsStatus } from "@/lib/types";

interface Props {
  /**
   * Milliseconds the connection must stay in `"closed"` before the banner
   * renders. Defaults to 3000. Exposed so tests and short-lived preview
   * harnesses can tune it; production callers should use the default.
   */
  debounceMs?: number;
}

export function DisconnectedBanner({ debounceMs = 3000 }: Props = {}): JSX.Element | null {
  const [status, setStatus] = useState<WsStatus>("connecting");
  const [show, setShow] = useState(false);

  useEffect(() => {
    const off = wsBus.on("__status", (m) => setStatus(m.status));
    return off;
  }, []);

  useEffect(() => {
    if (status === "closed") {
      const t = setTimeout(() => setShow(true), debounceMs);
      return () => clearTimeout(t);
    }
    setShow(false);
    return undefined;
  }, [status, debounceMs]);

  if (!show) return null;

  return (
    // S-349: the former fixed amber palette literals were migrated to the brand
    // `warn` token. The old amber text colour had no dark-theme variant and read
    // muddy on the dark `--bg`; `text-warn` (→ --warn) flips per theme.
    <div role="status" aria-live="polite" className="bg-warn/10 px-3 py-1 text-xs text-warn">
      Live stream disconnected — retrying…
    </div>
  );
}
