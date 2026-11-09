import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { Answer } from "../src/answer";
import { CorpusStats } from "../src/corpus-stats";
import { LIMITS } from "../src/limits";
import { listFixtures, readJson, root } from "./helpers";

const bytes = (v: unknown) => Buffer.byteLength(JSON.stringify(v), "utf8");
const str = (n: number, ch = "x") => ch.repeat(n);
const pid = `${str(LIMITS.docIdMaxChars - 7)}§${str(LIMITS.paragraphIdMaxChars - LIMITS.docIdMaxChars + 6)}`;

function citation() {
  return {
    paragraph_id: pid.slice(0, LIMITS.paragraphIdMaxChars),
    doc_id: str(LIMITS.docIdMaxChars),
    case_name: str(LIMITS.caseNameMaxChars),
    doc_type: "legal_summary" as const,
    quote: str(LIMITS.quoteMaxChars),
    link_target: str(LIMITS.linkMaxChars),
  };
}

function matchingCase() {
  const { paragraph_id, doc_id, case_name, doc_type, quote, link_target } = citation();
  return { doc_id, case_name, doc_type, paragraph_id, quote, link_target };
}

/** Every string, array and number at its schema maximum (ASCII text). */
export function worstCaseAnswer() {
  const step = (s: "route" | "retrieve" | "rerank" | "generate" | "verify") => ({
    step: s,
    model: str(LIMITS.modelNameMaxChars),
    tokens_in: 999_999_999,
    tokens_out: 999_999_999,
    tokens_cached: 999_999_999,
    cost_usd: 123456.123456,
    latency_ms: 123456.1,
  });
  return {
    request_id: str(LIMITS.requestIdMaxChars),
    question: str(LIMITS.questionMaxChars),
    route: "stats" as const,
    answer_text: str(LIMITS.answerTextMaxChars),
    claims: Array.from({ length: LIMITS.claimsMax }, (_, i) => ({
      id: str(16, String(i % 10)),
      text: str(LIMITS.claimTextMaxChars),
      citation_ids: Array.from({ length: LIMITS.claimCitationIdsMax }, () => citation().paragraph_id),
      status: "unsupported" as const,
      reason: str(LIMITS.claimReasonMaxChars),
    })),
    citations: Array.from({ length: LIMITS.citationsMax }, citation),
    stats: {
      question: str(LIMITS.questionMaxChars),
      sql: str(LIMITS.sqlMaxChars),
      columns: Array.from({ length: LIMITS.statsColumnsMax }, () => str(40)),
      rows: Array.from({ length: LIMITS.statsRowsMax }, () =>
        Array.from({ length: LIMITS.statsColumnsMax }, () => str(LIMITS.statsCellMaxChars)),
      ),
      matching_cases: Array.from({ length: LIMITS.matchingCasesMax }, matchingCase),
      count: 999_999_999,
      scope_total: 999_999_999,
      explanation: str(LIMITS.explanationMaxChars),
    },
    refused_or_not_in_sources: false,
    steps: Array.from({ length: LIMITS.stepsMax }, (_, i) => step(["route", "retrieve", "rerank", "generate", "verify"][i % 5] as "route")),
    total_cost_usd: 123456.123456,
    total_latency_ms: 123456.1,
    models_used: Array.from({ length: LIMITS.modelsMax }, () => str(LIMITS.modelNameMaxChars)),
  };
}

describe("Answer payload size (< 50 KB)", () => {
  it.each(listFixtures().filter((f) => f.name === "Answer").map((f) => f.file))("fixture %s", (file) => {
    expect(bytes(readJson(join(root, "fixtures", file)))).toBeLessThan(LIMITS.answerMaxBytes);
  });

  it("generated worst case is valid and still under the limit", () => {
    const worst = worstCaseAnswer();
    expect(Answer.safeParse(worst).error?.issues ?? []).toEqual([]);
    const size = bytes(worst);
    console.log(`worst-case Answer payload: ${size} bytes`);
    expect(size).toBeLessThan(LIMITS.answerMaxBytes);
  });

  it("one more element than any limit is rejected", () => {
    const w = worstCaseAnswer();
    expect(Answer.safeParse({ ...w, citations: [...w.citations, citation()] }).success).toBe(false);
    expect(Answer.safeParse({ ...w, answer_text: str(LIMITS.answerTextMaxChars + 1) }).success).toBe(false);
  });
});

describe("CorpusStats payload size", () => {
  it("fixture and generated worst case stay under the limit", () => {
    expect(bytes(readJson(join(root, "fixtures", "CorpusStats.json")))).toBeLessThan(LIMITS.corpusStatsMaxBytes);
    const bucket = (n: number) => Array.from({ length: n }, () => ({ key: str(40), count: 999_999_999 }));
    const run = {
      run_id: str(LIMITS.idMaxChars),
      data_source: "snapshot" as const,
      started_at: "2026-11-03T16:10:36Z",
      finished_at: "2026-11-03T16:13:05Z",
      stage_seconds: { download: 99999.999, parse: 99999.999, chunk: 99999.999, embed: 99999.999, index: 99999.999 },
      counts: { seen: 999_999_999, new: 999_999_999, changed: 999_999_999, unchanged_skipped: 999_999_999, failed: 999_999_999 },
      embedder_model: str(LIMITS.modelNameMaxChars),
      embedding_dim: 99999,
    };
    const usage = { calls: 999_999_999, tokens_in: 999_999_999, tokens_out: 999_999_999, tokens_cached: 999_999_999, cost_usd: 123456.123456 };
    const worst = {
      data_source: "snapshot" as const,
      generated_at: "2026-11-03T16:13:05Z",
      totals: { documents: 999_999_999, paragraphs: 999_999_999, chunks: { fixed: 999_999_999, recursive: 999_999_999, by_section: 999_999_999 } },
      by_doc_type: bucket(LIMITS.statsDocTypeBucketsMax),
      by_outcome: bucket(LIMITS.statsOutcomeBucketsMax),
      by_chamber: bucket(LIMITS.statsChamberBucketsMax),
      by_article: bucket(LIMITS.statsArticleBucketsMax),
      by_year: bucket(LIMITS.statsYearBucketsMax),
      last_ingest_run: run,
      costs: {
        total_usd: 123456.123456,
        since: "2026-11-03T16:13:05Z",
        by_purpose: Array.from({ length: LIMITS.costByPurposeMax }, () => ({ purpose: "generate" as const, ...usage })),
        by_model: Array.from({ length: LIMITS.costByModelMax }, () => ({ model: str(LIMITS.modelNameMaxChars), ...usage })),
        recent: Array.from({ length: LIMITS.costRecentMax }, () => ({
          id: str(LIMITS.idMaxChars),
          timestamp: "2026-11-03T16:13:05Z",
          model: str(LIMITS.modelNameMaxChars),
          purpose: "generate" as const,
          tokens_in: 999_999_999,
          tokens_out: 999_999_999,
          tokens_cached: 999_999_999,
          cost_usd: 123456.123456,
          latency_ms: 123456.1,
          request_id: str(LIMITS.idMaxChars),
        })),
      },
      latest_eval: {
        run_id: str(LIMITS.idMaxChars),
        started_at: "2026-11-03T16:13:05Z",
        finished_at: "2026-11-03T16:13:05Z",
        data_source: "snapshot" as const,
        config: { chunking: "by_section" as const, mode: "hybrid_rerank" as const, rerank: true, embedder_model: str(LIMITS.modelNameMaxChars), generator_model: str(LIMITS.modelNameMaxChars), judge_model: str(LIMITS.modelNameMaxChars) },
        metrics: { recall_at_5: 0.123456789, recall_at_10: 0.123456789, mrr: 0.123456789, faithfulness: 0.123456789, citation_accuracy: 0.123456789, neutrality: 0.123456789 },
        cost_usd: 123456.123456,
        tokens_in: 999_999_999,
        tokens_out: 999_999_999,
        timings_ms: { total: 123456.1, mean_per_item: 123456.1 },
        item_count: 500,
      },
    };
    expect(CorpusStats.safeParse(worst).error?.issues ?? []).toEqual([]);
    const size = bytes(worst);
    console.log(`worst-case CorpusStats payload: ${size} bytes`);
    expect(size).toBeLessThan(LIMITS.corpusStatsMaxBytes);
  });
});
