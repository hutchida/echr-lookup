import {
  Answer,
  AnswerRequest,
  ApiError,
  CaseDetail,
  CorpusStats,
  CostSummary,
  EvalRun,
  EvalRunList,
  Health,
  IngestRunList,
  SearchRequest,
  SearchResult,
} from "@echr/contract";

/**
 * Typed client for the FastAPI service. Server-side only: call it from Server Components,
 * Server Actions or Route Handlers, never from the browser (API_URL is not public and the
 * API only allows CORS from ports 3000/3100).
 */
export const API_URL = process.env.API_URL ?? "http://localhost:8000";

/** Every call returns this: parsed contract data, or a readable error (with the API's ApiError body when it sent one). */
export type ApiResult<T> =
  | { ok: true; data: T; ms: number }
  | { ok: false; error: string; status: number | null; apiError: ApiError | null; ms: number };

type Schema<T> = {
  safeParse(value: unknown): { success: true; data: T } | { success: false; error: { message: string } };
};

export type ApiOptions = { baseUrl?: string; fetchImpl?: typeof fetch };

async function call<T>(
  schema: Schema<T>,
  path: string,
  init: RequestInit | undefined,
  { baseUrl = API_URL, fetchImpl = fetch }: ApiOptions = {},
): Promise<ApiResult<T>> {
  const started = performance.now();
  const ms = () => Math.round(performance.now() - started);
  try {
    const res = await fetchImpl(`${baseUrl}${path}`, { cache: "no-store", ...init });
    const body: unknown = await res.json().catch(() => null);
    if (!res.ok) {
      const parsed = ApiError.safeParse(body);
      const apiError = parsed.success ? parsed.data : null;
      const error = apiError
        ? `${apiError.error}${apiError.detail ? `: ${apiError.detail}` : ""}`
        : `API returned HTTP ${res.status}`;
      return { ok: false, error, status: res.status, apiError, ms: ms() };
    }
    const parsed = schema.safeParse(body);
    if (!parsed.success) {
      return {
        ok: false,
        error: `API reply did not match the contract: ${parsed.error.message}`,
        status: res.status,
        apiError: null,
        ms: ms(),
      };
    }
    return { ok: true, data: parsed.data, ms: ms() };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err), status: null, apiError: null, ms: ms() };
  }
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

/** POST /search */
export const search = (req: SearchRequest, opts?: ApiOptions) => call(SearchResult, "/search", post(req), opts);
/** POST /ask (5–10 s on the RAG route; it calls Claude) */
export const ask = (req: AnswerRequest, opts?: ApiOptions) => call(Answer, "/ask", post(req), opts);
/** GET /stats */
export const getStats = (opts?: ApiOptions) => call(CorpusStats, "/stats", undefined, opts);
/** GET /case/{id} */
export const getCase = (id: string, opts?: ApiOptions) =>
  call(CaseDetail, `/case/${encodeURIComponent(id)}`, undefined, opts);
/** GET /ingest-runs (newest first) */
export const getIngestRuns = (opts?: ApiOptions) => call(IngestRunList, "/ingest-runs", undefined, opts);
/** GET /eval-runs */
export const getEvalRuns = (opts?: ApiOptions) => call(EvalRunList, "/eval-runs", undefined, opts);
/** GET /eval-runs/{id} */
export const getEvalRun = (id: string, opts?: ApiOptions) =>
  call(EvalRun, `/eval-runs/${encodeURIComponent(id)}`, undefined, opts);
/** GET /costs */
export const getCosts = (opts?: ApiOptions) => call(CostSummary, "/costs", undefined, opts);

export type HealthResult =
  | { ok: true; health: Health; ms: number }
  | { ok: false; error: string };

/** Calls the FastAPI /health endpoint and checks the reply against the shared contract. */
export async function getHealth(
  baseUrl: string = API_URL,
  fetchImpl: typeof fetch = fetch,
): Promise<HealthResult> {
  const r = await call(Health, "/health", undefined, { baseUrl, fetchImpl });
  return r.ok ? { ok: true, health: r.data, ms: r.ms } : { ok: false, error: r.error };
}
