/* eslint-disable no-console */

// __DEV__ is exposed on globalThis so Vitest tests can stub it via
// vi.stubGlobal("__DEV__", false) to exercise the production code path.
// (import.meta.env.DEV is a compile-time literal in Vite/Vitest and cannot
// be changed at runtime via vi.stubEnv — it is always `true` in test mode.)
declare global {
  // eslint-disable-next-line no-var
  var __DEV__: boolean | undefined;
}

if (typeof globalThis.__DEV__ === "undefined") {
  globalThis.__DEV__ = import.meta.env.DEV;
}

export const logger = {
  info:  (...a: unknown[]) => { if (globalThis.__DEV__) console.info(...a); },
  warn:  (...a: unknown[]) => { if (globalThis.__DEV__) console.warn(...a); },
  error: (...a: unknown[]) => console.error(...a),
};
