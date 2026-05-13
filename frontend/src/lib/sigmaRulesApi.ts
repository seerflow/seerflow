// S-151: REST client for the /api/v1/sigma/rules endpoints.
//
// Each helper validates the response body via the corresponding valibot
// schema; failures throw ApiError with the schema diagnostic so the UI
// surfaces "we got a malformed response" rather than crashing on a typo.
import { api } from "./api";
import {
  SigmaRuleDetailSchema,
  SigmaRuleListResponseSchema,
  SigmaRuleTimelineResponseSchema,
  SigmaRuleValidationResultSchema,
} from "./schemas";
import type {
  SigmaRuleDetail,
  SigmaRuleListResponse,
  SigmaRuleSource,
  SigmaRuleTimelineBucketSpan,
  SigmaRuleTimelineResponse,
  SigmaRuleTimelineWindow,
  SigmaRuleValidationResult,
} from "./types";

export interface ListParams {
  page?: number;
  limit?: number;
  category?: string;
  // S-154 (T8): backend expects repeated `?severity_in=N` query params and
  // treats the empty list / missing param as "no filter". Empty arrays MUST
  // be omitted from the URL — see buildQuery() below.
  severity_in?: number[];
  logsource_product?: string;
  enabled?: boolean;
  source?: SigmaRuleSource;
  search?: string;
}

function buildQuery(params: ListParams): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (k === "severity_in" && Array.isArray(v)) {
      // Empty list = no filter; skip to avoid `?severity_in=` no-op tokens
      // hitting the backend's empty-token-strip path unnecessarily.
      if (v.length === 0) continue;
      for (const sev of v) qs.append("severity_in", String(sev));
      continue;
    }
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

// S-154 (T8): Fetch the dense 24-bucket hourly firing trend for a rule.
// `bucket=hour&window=24h` is the only supported combo today; the backend
// returns a 404 only when the rule id is unknown (an empty alert window
// is a 200 with 24 zero buckets), so callers should treat fetch errors as
// "hide the sparkline" rather than "rule disappeared".
export async function getSigmaRuleTimeline(
  ruleId: string,
  signal?: AbortSignal,
  bucket: SigmaRuleTimelineBucketSpan = "hour",
  window: SigmaRuleTimelineWindow = "24h",
): Promise<SigmaRuleTimelineResponse> {
  return api.get<SigmaRuleTimelineResponse>(
    `/api/v1/sigma/rules/${encodeURIComponent(ruleId)}/timeline?bucket=${bucket}&window=${window}`,
    { schema: SigmaRuleTimelineResponseSchema, signal },
  );
}
