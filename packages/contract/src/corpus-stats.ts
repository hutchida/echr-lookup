import { z } from "zod";
import { CostSummary } from "./cost-summary";
import { EvalRunSummary } from "./eval";
import { IngestRun } from "./ingest-run";
import { LIMITS } from "./limits";
import { Count, DataSource, IsoDateTime } from "./shared";

/** One bar of a breakdown. `key` null = documents with no value for that field (e.g. no chamber). */
export const CountBucket = z.strictObject({
  key: z.string().max(40).nullable(),
  count: Count,
});

export const CorpusStats = z
  .strictObject({
    data_source: DataSource,
    generated_at: IsoDateTime,
    totals: z.strictObject({
      documents: Count,
      paragraphs: Count,
      chunks: z.strictObject({ fixed: Count, recursive: Count, by_section: Count }).describe("chunks built per strategy"),
    }),
    by_doc_type: z.array(CountBucket).max(LIMITS.statsDocTypeBucketsMax).describe("sums to totals.documents"),
    by_outcome: z.array(CountBucket).max(LIMITS.statsOutcomeBucketsMax).describe("normalised outcome; sums to totals.documents"),
    by_chamber: z.array(CountBucket).max(LIMITS.statsChamberBucketsMax).describe("key null = no chamber; sums to totals.documents"),
    by_article: z
      .array(CountBucket)
      .max(LIMITS.statsArticleBucketsMax)
      .describe("top articles by number of documents, most frequent first; sub-paragraphs folded (8-1 counts as 8, 14+8 as 14)"),
    by_year: z.array(CountBucket).max(LIMITS.statsYearBucketsMax).describe("key = year of `date`, ascending; sums to totals.documents"),
    last_ingest_run: IngestRun.nullable(),
    costs: CostSummary,
    latest_eval: EvalRunSummary.nullable(),
  })
  .meta({ id: "CorpusStats", description: "GET /stats response: what is in the corpus and how the system has been running" });

export type CorpusStats = z.infer<typeof CorpusStats>;
