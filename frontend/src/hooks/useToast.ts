import { toast } from "sonner";

const SUCCESS_MS = 3000;
const ERROR_MS = 5000;

/**
 * Thin wrapper around sonner that pins success/error durations to the
 * product-defined values (3 s success, 5 s error — S-066). Non-React
 * callers can import the module-level durations instead.
 */
export function useToast(): {
  success: (message: string) => void;
  error: (message: string) => void;
} {
  return {
    success: (message) => { toast.success(message, { duration: SUCCESS_MS }); },
    error: (message) => { toast.error(message, { duration: ERROR_MS }); },
  };
}
