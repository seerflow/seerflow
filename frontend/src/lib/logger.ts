/* eslint-disable no-console */

/**
 * Pure logger factory. Exported so tests can construct a logger with an
 * arbitrary `dev` flag and exercise both code paths without stubbing
 * `import.meta.env` (which Vite static-replaces at build time).
 */
export function makeLogger(dev: boolean) {
  return {
    info:  dev ? (...a: unknown[]) => console.info(...a) : () => {},
    warn:  dev ? (...a: unknown[]) => console.warn(...a) : () => {},
    error: (...a: unknown[]) => console.error(...a),
  };
}

// Production binding. Vite replaces `import.meta.env.DEV` with a literal at
// build time, so the unused arm of each ternary becomes dead code.
export const logger = makeLogger(import.meta.env.DEV);
