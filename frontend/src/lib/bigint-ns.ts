/**
 * Shared helpers for the JS-bigint-safe `*_ns` wire format (S-194 / S-199).
 *
 * Lives in its own tiny module so that consumers of `@/lib/api` that only need
 * the boundary helpers (e.g. the WebSocket hook) do not drag in the fetch
 * wrapper, and so test files that `vi.mock("@/lib/api", ...)` do not have to
 * re-export these constants on every mock.
 */

/**
 * Upper bound on the decimal length of a nanosecond timestamp string before
 * we refuse to call BigInt() on it. A 25-digit value encodes ~3×10^16 seconds
 * (roughly 10^9 years past the epoch), well above any real wire timestamp. The
 * cap defends the client against a malicious/buggy peer that sends a giant
 * digit string — BigInt construction is O(n^2) in the digit count and will
 * block the UI thread for seconds on megabyte-scale inputs.
 */
export const MAX_NS_STRING_LEN = 25;

/**
 * Safe-guarded string → bigint conversion for the `*_ns` wire fields.
 * Returns the raw string back unchanged when the input is malformed or too
 * long so callers (REST walker, WS dispatch) degrade gracefully instead of
 * crashing or hanging.
 */
export function toBigintNs(v: string): bigint | string {
  if (v.length === 0 || v.length > MAX_NS_STRING_LEN) return v;
  try { return BigInt(v); }
  catch { return v; }
}
