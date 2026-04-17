import { useEffect, useState } from "react";
import type { WsStatus } from "@/lib/types";

export function DisconnectedBanner({ status }: { status: WsStatus }): JSX.Element | null {
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (status === "closed") {
      const t = setTimeout(() => setShow(true), 3000);
      return () => clearTimeout(t);
    }
    setShow(false);
    return undefined;
  }, [status]);

  if (!show) return null;

  return (
    <div role="status" aria-live="polite" className="bg-amber-500/10 px-3 py-1 text-xs text-amber-700">
      Live stream disconnected — retrying…
    </div>
  );
}
