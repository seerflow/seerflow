import { useCallback, useEffect, useRef } from "react";
import type { WsStatus, WsFilter, WireWsMessage } from "@/lib/types";
import { logger } from "@/lib/logger";
import { parseWsFrame } from "@/lib/schemas";

interface Opts {
  onMessage: (m: WireWsMessage) => void;
  onStatusChange: (s: WsStatus) => void;
  getFilterMessage?: () => WsFilter | null;
}

const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000, 30000];

export function useWebSocket(url: string, opts: Opts): { send: (m: unknown) => void } {
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queueRef = useRef<unknown[]>([]);
  const optsRef = useRef(opts);
  optsRef.current = opts;

  useEffect(() => {
    let cancelled = false;

    const connect = (): void => {
      optsRef.current.onStatusChange("connecting");
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) { ws.close(); return; }
        retryRef.current = 0;
        optsRef.current.onStatusChange("open");
        const filter = optsRef.current.getFilterMessage?.();
        if (filter) ws.send(JSON.stringify(filter));
        for (const m of queueRef.current) ws.send(JSON.stringify(m));
        queueRef.current = [];
      };
      ws.onmessage = (ev) => {
        let raw: unknown;
        try { raw = JSON.parse(ev.data); }
        catch (e) { logger.warn("ws parse fail", e); return; }
        const msg = parseWsFrame(raw);
        if (!msg) return;
        optsRef.current.onMessage(msg);
      };
      ws.onerror = () => logger.warn("ws error");
      ws.onclose = () => {
        optsRef.current.onStatusChange("closed");
        if (cancelled) return;
        const delay = BACKOFF_MS[Math.min(retryRef.current, BACKOFF_MS.length - 1)];
        retryRef.current++;
        timerRef.current = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [url]);

  const send = useCallback((m: unknown): void => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(m));
    else queueRef.current.push(m);
  }, []);

  return { send };
}
