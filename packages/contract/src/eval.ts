import { z } from "zod";
import { LIMITS } from "./limits";
import { ChunkStrategy, Count, DataSource, IsoDateTime, ParagraphId, Score01, SearchMode } from "./shared";

export const EvalItem = z
  .strictObject({
    id: z.string().min(1),
    question: z.string().min(1),
    type: z.enum(["explain", "stat", "neutrality"]),
    expected_paragraph_ids: z.array(ParagraphId).describe("empty for stat and some neutrality items"),
    reference_notes: z.string().describe("what a good answer says, in plain words"),
    status: z.enum(["draft", "reviewed"]),
    tags: z.array(z.string()),
  })
  .meta({ id: "EvalItem", description: "One evaluation question with its expected evidence" });

const nullableScore = Score01.nullable();

export const EvalItemResult = z.strictObject({
  item_id: z.string().min(1),
  retrieved_paragraph_ids: z.array(ParagraphId).max(10).describe("top-10 paragraph ids, best first"),
  recall_at_5: nullableScore,
  recall_at_10: nullableScore,
  reciprocal_rank: nullableScore,
  faithfulness: nullableScore,
  citation_accuracy: nullableScore,
  neutrality: nullableScore,
  latency_ms: z.number().min(0),
});

const evalRunBase = {
  run_id: z.string().min(1).max(LIMITS.idMaxChars),
  started_at: IsoDateTime,
  finished_at: IsoDateTime,
  data_source: DataSource,
  config: z.strictObject({
    chunking: ChunkStrategy,
    mode: SearchMode,
    rerank: z.boolean(),
    embedder_model: z.string().min(1).max(LIMITS.modelNameMaxChars),
    generator_model: z.string().max(LIMITS.modelNameMaxChars).nullable().describe("null for retrieval-only runs"),
    judge_model: z.string().max(LIMITS.modelNameMaxChars).nullable(),
  }),
  metrics: z.strictObject({
    recall_at_5: nullableScore,
    recall_at_10: nullableScore,
    mrr: nullableScore,
    faithfulness: nullableScore,
    citation_accuracy: nullableScore,
    neutrality: nullableScore,
  }),
  cost_usd: z.number().min(0),
  tokens_in: Count,
  tokens_out: Count,
  timings_ms: z.strictObject({ total: z.number().min(0), mean_per_item: z.number().min(0) }),
};

export const EvalRun = z
  .strictObject({
    ...evalRunBase,
    items: z.array(EvalItemResult).max(LIMITS.evalItemsMax),
  })
  .meta({
    id: "EvalRun",
    description: "Result of running the eval set under one configuration (GET /eval-runs/{id})",
  });

/** An EvalRun without the per-item results: what the stats page and GET /eval-runs need. */
export const EvalRunSummary = z
  .strictObject({
    ...evalRunBase,
    item_count: Count.describe("number of items in the full EvalRun (its `items` are omitted here)"),
  })
  .meta({ id: "EvalRunSummary", description: "EvalRun without per-item results (element of GET /eval-runs, and CorpusStats.latest_eval)" });

export type EvalItem = z.infer<typeof EvalItem>;
export type EvalRun = z.infer<typeof EvalRun>;
export type EvalRunSummary = z.infer<typeof EvalRunSummary>;
