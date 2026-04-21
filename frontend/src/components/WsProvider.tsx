import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import { logger } from "@/lib/logger";
import * as wsBus from "@/lib/wsBus";
import { merged as mergedWsFilter } from "@/lib/wsFilter";
import type { WsMessage, WsStatus } from "@/lib/types";

type SendFn = (msg: unknown) => void;
const Ctx = createContext<SendFn | null>(null);

function resolveUrl(): string {
  const base = (import.meta.env.VITE_API_BASE as string | undefined) ?? window.location.origin;
  const url = base.replace(/^http/, "ws") + "/api/v1/ws";
  if (url.startsWith("ws:") && window.location.protocol === "https:") {
    logger.warn("WebSocket URL is insecure (ws:) but page served over https:", url);
  }
  return url;
}

export function WsProvider({ children }: { children: ReactNode }): JSX.Element {
  const url = useMemo(resolveUrl, []);
  const { send } = useWebSocket(url, {
    onMessage: (m: WsMessage) => wsBus.emit(m),
    onStatusChange: (s: WsStatus) => wsBus.emit({ type: "__status", status: s }),
    // Replay the current merged filter on every (re)connect so the server
    // resumes honoring widget filters without waiting for the 150 ms debounce
    // in each widget's filter-push effect to re-fire.
    getFilterMessage: () => mergedWsFilter(),
  });
  return <Ctx.Provider value={send}>{children}</Ctx.Provider>;
}

// react-refresh warns about co-locating hooks with components; intentional
// here — `useWsSend` reads the same module-scoped Context the provider
// creates, so splitting them would require a third private module.
// eslint-disable-next-line react-refresh/only-export-components
export function useWsSend(): SendFn {
  const v = useContext(Ctx);
  if (!v) throw new Error("useWsSend must be used inside <WsProvider>");
  return v;
}
