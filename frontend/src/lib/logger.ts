/* eslint-disable no-console */
export const logger = {
  info:  import.meta.env.DEV ? (...a: unknown[]) => console.info(...a) : () => {},
  warn:  import.meta.env.DEV ? (...a: unknown[]) => console.warn(...a) : () => {},
  error: (...a: unknown[]) => console.error(...a),
};
