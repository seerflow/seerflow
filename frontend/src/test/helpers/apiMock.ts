import { vi } from "vitest";
import * as v from "valibot";
import { validateOrDropItem } from "@/lib/schemas";

export interface MockGetOpts {
  schema?: unknown;
  itemsKey?: string;
  signal?: AbortSignal;
}

export class DefaultMockApiError extends Error {
  status: number;
  cause: unknown;
  constructor(status: number, message: string, cause?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.cause = cause;
  }
}

type ErrorCtor = new (status: number, message: string, cause?: unknown) => Error;

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
  fetchMock?: (method: "GET", path: string, opts?: MockGetOpts) => unknown | Promise<unknown>;
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
