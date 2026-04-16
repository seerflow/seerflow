import { useCallback, useEffect, useRef } from "react";
import * as v from "valibot";
import type { WsStatus, WsFilter, WsMessage } from "@/lib/types";
import { logger } from "@/lib/logger";

interface Opts {
  onMessage: (m: WsMessage) => void;
  onStatusChange: (s: WsStatus) => void;
  getFilterMessage?: () => WsFilter | null;
}

const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000, 30000];

// S-194 AC-2: shallow runtime schema for incoming WS frames. Validates the
// discriminator and the fields each consumer reads at the top level only.
// Deeper validation would duplicate backend models with little real-world
// payoff (see Brainstorm Note #4 in docs/stories/S-194.md).
// looseObject is used so that extra fields beyond the validated minimum are
// preserved and passed through to consumers unchanged.
const AlertDataSchema = v.looseObject({
  alert_id: v.string(),
  timestamp_ns: v.pipe(v.string(), v.regex(/^\d+$/)),
});

const StatusDataSchema = v.looseObject({
  events_ingested_per_sec: v.number(),
  alerts_24h: v.number(),
  connected_clients: v.number(),
  dropped_events: v.number(),
  dropped_alerts: v.number(),
  dropped_total: v.number(),
});

const EventDataSchema = v.looseObject({});  // event payload shape varies; keep open

const WsMessageSchema = v.union([
  v.object({ type: v.literal("alert"),       data: AlertDataSchema }),
  v.object({ type: v.literal("alert_batch"), alerts: v.array(AlertDataSchema) }),
  v.object({ type: v.literal("status"),      data: StatusDataSchema }),
  v.object({ type: v.literal("event"),       data: EventDataSchema }),
  v.object({ type: v.literal("batch"),       events: v.array(v.unknown()) }),
]);

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
        const result = v.safeParse(WsMessageSchema, raw);
        if (!result.success) {
          // S-194: log only diagnostic shape (kind/type/path), not raw `input`/`received` —
          // the rejected frame may contain PII (entity_value, rule_name, etc.).
          logger.warn(
            "ws schema mismatch",
            result.issues.map(i => ({ kind: i.kind, type: i.type, path: i.path?.map(p => p.key) })),
          );
          return;
        }
        const msg = result.output;
        try {
          if (msg.type === "alert") {
            // S-194 AC-1: convert string wire timestamp into bigint at the boundary.
            const data = { ...msg.data, timestamp_ns: BigInt(msg.data.timestamp_ns) };
            optsRef.current.onMessage({ type: "alert", data } as unknown as WsMessage);
          } else if (msg.type === "alert_batch") {
            // S-194: convert each alert's string timestamp_ns to bigint before dispatch.
            const alerts = msg.alerts.map(a => ({ ...a, timestamp_ns: BigInt(a.timestamp_ns) }));
            optsRef.current.onMessage({ type: "alert_batch", alerts } as unknown as WsMessage);
          } else {
            optsRef.current.onMessage(msg as unknown as WsMessage);
          }
        } catch (e) {
          logger.warn("ws timestamp conversion failed", e);
        }
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
