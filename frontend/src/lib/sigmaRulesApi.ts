// S-151: REST client for the /api/v1/sigma/rules endpoints.
//
// Each helper validates the response body via the corresponding valibot
// schema; failures throw ApiError with the schema diagnostic so the UI
// surfaces "we got a malformed response" rather than crashing on a typo.
import { api, ApiError } from "./api";
import {
  SigmaRuleDetailSchema,
  SigmaRuleListResponseSchema,
  SigmaRuleValidationResultSchema,
} from "./schemas";
import type {
  SigmaRuleDetail,
  SigmaRuleListResponse,
  SigmaRuleSource,
  SigmaRuleValidationResult,
} from "./types";

export interface ListParams {
  page?: number;
  limit?: number;
  category?: string;
  severity?: number;
  logsource_product?: string;
  enabled?: boolean;
  source?: SigmaRuleSource;
  search?: string;
}

function buildQuery(params: ListParams): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export async function getSigmaRules(
  params: ListParams = {},
  signal?: AbortSignal,
): Promise<SigmaRuleListResponse> {
  return api.get<SigmaRuleListResponse>(`/api/v1/sigma/rules${buildQuery(params)}`, {
    schema: SigmaRuleListResponseSchema,
    signal,
  });
}

export async function getSigmaRule(
  ruleId: string,
  signal?: AbortSignal,
): Promise<SigmaRuleDetail> {
  return api.get<SigmaRuleDetail>(`/api/v1/sigma/rules/${encodeURIComponent(ruleId)}`, {
    schema: SigmaRuleDetailSchema,
    signal,
  });
}

export async function toggleSigmaRule(
  ruleId: string,
  enabled: boolean,
): Promise<SigmaRuleDetail> {
  // The shared `api.post` wrapper builds a POST; PATCH must be issued via
  // raw fetch for now. Mirror the request/respond shape (envelope + valibot
  // validation) so error handling stays uniform.
  const path = `/api/v1/sigma/rules/${encodeURIComponent(ruleId)}`;
  const base = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";
  const res = await fetch(`${base}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ enabled }),
  });
  const text = await res.text();
  let parsed: unknown = text;
  try {
    parsed = text ? JSON.parse(text) : text;
  } catch {
    // fall through with raw text
  }
  if (!res.ok) {
    const detail =
      parsed && typeof parsed === "object" && "detail" in parsed
        ? String((parsed as { detail: unknown }).detail)
        : text;
    throw new ApiError(res.status, detail);
  }
  const result = (await import("valibot")).safeParse(SigmaRuleDetailSchema, parsed);
  if (!result.success) {
    throw new ApiError(0, `response-schema-fail: ${result.issues.map((i) => i.message).join("; ")}`);
  }
  return result.output as SigmaRuleDetail;
}

export async function validateSigmaRule(
  yaml: string,
): Promise<SigmaRuleValidationResult> {
  return api.post<SigmaRuleValidationResult>(
    `/api/v1/sigma/rules?dry_run=true`,
    { yaml },
    { schema: SigmaRuleValidationResultSchema },
  );
}

export async function uploadSigmaRule(yaml: string): Promise<SigmaRuleDetail> {
  return api.post<SigmaRuleDetail>(`/api/v1/sigma/rules`, { yaml }, {
    schema: SigmaRuleDetailSchema,
  });
}
