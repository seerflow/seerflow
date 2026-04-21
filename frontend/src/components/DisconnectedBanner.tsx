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
    <div role="status" aria-live="polite" className="bg-amber-500/10 px-3 py-1 text-xs text-amber-700">
      Live stream disconnected — retrying…
    </div>
  );
}
