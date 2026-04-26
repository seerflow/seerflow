import { vi } from "vitest";
import * as v from "valibot";
import { validateOrDropItem } from "@/lib/schemas";

export interface MockGetOpts {
  schema?: unknown;
  itemsKey?: string;
  signal?: AbortSignal;
}

// 4-param signature mirrors `frontend/src/lib/api.ts::ApiError`
// (status, detail, debugDetail?, cause?) so passing the real ApiError
// class as `ApiErrorClass` is type-compatible.
export class DefaultMockApiError extends Error {
  status: number;
  debugDetail?: string;
  cause: unknown;
  constructor(status: number, detail: string, debugDetail?: string, cause?: unknown) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.debugDetail = debugDetail;
    this.cause = cause;
  }
}

type ErrorCtor = new (
  status: number,
  detail: string,
  debugDetail?: string,
  cause?: unknown,
) => Error;

export function applySchemaValidation<T>(
  body: T,
  path: string,
  opts: MockGetOpts | undefined,
  ErrorClass: ErrorCtor = DefaultMockApiError,
): T {
  if (!opts?.schema) return body;
  if (opts.itemsKey) {
    if (
      !body ||
      typeof body !== "object" ||
      !(opts.itemsKey in (body as Record<string, unknown>)) ||
      !Array.isArray((body as Record<string, unknown>)[opts.itemsKey])
    ) {
      throw new ErrorClass(0, `response-schema-fail: expected array at "${opts.itemsKey}"`);
    }
    const kind = `rest:${path.split("?")[0]}`;
    const raw = (body as Record<string, unknown>)[opts.itemsKey] as unknown[];
    const items = raw
      .map(item =>
        validateOrDropItem(
          opts.schema as Parameters<typeof validateOrDropItem>[0],
          item,
          kind,
        ),
      )
      .filter((x): x is NonNullable<typeof x> => x !== null);
    return { ...(body as Record<string, unknown>), [opts.itemsKey]: items } as T;
  }
  const parsed = v.safeParse(
    opts.schema as Parameters<typeof v.safeParse>[0],
    body,
  );
  if (!parsed.success) {
    throw new ErrorClass(
      0,
      `response-schema-fail: ${parsed.issues.map(i => i.message).join("; ")}`,
    );
  }
  return parsed.output as T;
}

export interface CreateApiMockOptions {
  // `createApiMock` itself only ever invokes this with "GET". The wider
  // union exists so user code that routes its own POST calls through the
  // same vi.fn (e.g. `postImpl: (...a) => fetchMock("POST", ...a)`) keeps
  // a uniform call signature.
  fetchMock?: (method: "GET" | "POST", path: string, opts?: MockGetOpts) => unknown | Promise<unknown>;
  defaultGetResponse?: unknown;
  postImpl?: (...args: unknown[]) => unknown;
  ApiErrorClass?: ErrorCtor;
}

export function createApiMock(options: CreateApiMockOptions = {}): {
  api: {
    get: ReturnType<typeof vi.fn>;
    post: ReturnType<typeof vi.fn> | ((...args: unknown[]) => unknown);
  };
  ApiError: ErrorCtor;
} {
  const ErrorClass = options.ApiErrorClass ?? DefaultMockApiError;
  const get = vi.fn(async (path: string, opts?: MockGetOpts) => {
    const res = options.fetchMock
      ? await options.fetchMock("GET", path, opts)
      : options.defaultGetResponse;
    return applySchemaValidation(res, path, opts, ErrorClass);
  });
  return {
    api: {
      get,
      post: options.postImpl ?? vi.fn(),
    },
    ApiError: ErrorClass,
  };
}
