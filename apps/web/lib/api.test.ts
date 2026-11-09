import { describe, expect, it } from "vitest";
import answer from "@echr/contract/fixtures/Answer.json";
import answerRequest from "@echr/contract/fixtures/AnswerRequest.json";
import apiError from "@echr/contract/fixtures/ApiError.json";
import caseDetail from "@echr/contract/fixtures/CaseDetail.json";
import corpusStats from "@echr/contract/fixtures/CorpusStats.json";
import costSummary from "@echr/contract/fixtures/CostSummary.json";
import evalRun from "@echr/contract/fixtures/EvalRun.json";
import evalRunList from "@echr/contract/fixtures/EvalRunList.json";
import health from "@echr/contract/fixtures/Health.json";
import ingestRunList from "@echr/contract/fixtures/IngestRunList.json";
import searchRequest from "@echr/contract/fixtures/SearchRequest.json";
import searchResult from "@echr/contract/fixtures/SearchResult.json";
import type { AnswerRequest, SearchRequest } from "@echr/contract";
import {
  ask,
  getCase,
  getCosts,
  getEvalRun,
  getEvalRuns,
  getHealth,
  getIngestRuns,
  getStats,
  search,
} from "./api";

type Seen = { url: string; method: string; body: unknown };

/** A fetch stand-in that records the request and replies with `body`. */
function fakeFetch(body: unknown, status = 200) {
  const seen: Seen[] = [];
  const impl = (async (url: string, init?: RequestInit) => {
    seen.push({
      url,
      method: init?.method ?? "GET",
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    return new Response(JSON.stringify(body), { status });
  }) as unknown as typeof fetch;
  return { impl, seen };
}

describe("getHealth", () => {
  it("accepts a reply that matches the contract", async () => {
    const r = await getHealth("http://api", fakeFetch(health).impl);
    expect(r.ok).toBe(true);
  });

  it("rejects a reply that breaks the contract", async () => {
    const r = await getHealth("http://api", fakeFetch({ status: "ok" }).impl);
    expect(r).toMatchObject({ ok: false });
  });

  it("reports HTTP errors", async () => {
    const r = await getHealth("http://api", fakeFetch({}, 503).impl);
    expect(r).toEqual({ ok: false, error: "API returned HTTP 503" });
  });
});

describe("typed client", () => {
  const cases = [
    ["search", (o: object) => search(searchRequest as SearchRequest, o), searchResult, "POST", "/search", searchRequest],
    ["ask", (o: object) => ask(answerRequest as AnswerRequest, o), answer, "POST", "/ask", answerRequest],
    ["getStats", (o: object) => getStats(o), corpusStats, "GET", "/stats", undefined],
    ["getCase", (o: object) => getCase("001-57619", o), caseDetail, "GET", "/case/001-57619", undefined],
    ["getIngestRuns", (o: object) => getIngestRuns(o), ingestRunList, "GET", "/ingest-runs", undefined],
    ["getEvalRuns", (o: object) => getEvalRuns(o), evalRunList, "GET", "/eval-runs", undefined],
    ["getEvalRun", (o: object) => getEvalRun("run 1", o), evalRun, "GET", "/eval-runs/run%201", undefined],
    ["getCosts", (o: object) => getCosts(o), costSummary, "GET", "/costs", undefined],
  ] as const;

  it.each(cases)("%s parses its fixture and calls the right endpoint", async (_n, fn, fixture, method, path, body) => {
    const f = fakeFetch(fixture);
    const r = await fn({ baseUrl: "http://api", fetchImpl: f.impl });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.data).toEqual(fixture);
    expect(f.seen).toEqual([{ url: `http://api${path}`, method, body }]);
  });

  it.each(cases)("%s rejects a reply that breaks the contract", async (_n, fn) => {
    const r = await fn({ baseUrl: "http://api", fetchImpl: fakeFetch({ nope: true }).impl });
    expect(r).toMatchObject({ ok: false, status: 200, apiError: null });
  });

  it("surfaces the API's ApiError body on a non-2xx status", async () => {
    const r = await getCase("001-99999", { baseUrl: "http://api", fetchImpl: fakeFetch(apiError, 404).impl });
    expect(r).toMatchObject({ ok: false, status: 404, apiError });
    if (!r.ok) expect(r.error).toMatch(/^not_found: No document/);
  });

  it("reports network failures without throwing", async () => {
    const boom = (async () => {
      throw new Error("connect ECONNREFUSED");
    }) as unknown as typeof fetch;
    const r = await getStats({ baseUrl: "http://api", fetchImpl: boom });
    expect(r).toMatchObject({ ok: false, status: null, error: "connect ECONNREFUSED" });
  });
});
