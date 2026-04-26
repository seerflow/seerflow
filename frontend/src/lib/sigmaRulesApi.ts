// S-151: REST client for the /api/v1/sigma/rules endpoints.
//
// Each helper validates the response body via the corresponding valibot
// schema; failures throw ApiError with the schema diagnostic so the UI
// surfaces "we got a malformed response" rather than crashing on a typo.
import { api } from "./api";
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
  return api.patch<SigmaRuleDetail>(
    `/api/v1/sigma/rules/${encodeURIComponent(ruleId)}`,
    { enabled },
    { schema: SigmaRuleDetailSchema },
  );
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
