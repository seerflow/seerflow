import { useCallback, useEffect, useRef } from "react";

/**
 * Debounced WS send hook. Returns a stable dispatcher that forwards to `send`
 * after `delay` ms of inactivity; rapid calls coalesce to the latest value.
 *
 * - Uses a ref for the latest `send` fn so consumers do not need to memoize it.
 * - Cancels any pending timer on unmount and when `delay` changes.
 */
export function useDebouncedWsSend<T>(
  send: (v: T) => void,
  delay: number,
): (v: T) => void {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sendRef = useRef(send);
  sendRef.current = send;

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [delay]);

  return useCallback(
    (v: T) => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        sendRef.current(v);
      }, delay);
    },
    [delay],
  );
}
