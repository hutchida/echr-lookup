import { z } from "zod";
import { LIMITS } from "./limits";
import { Count, DataSource, IsoDateTime } from "./shared";

const seconds = z.number().min(0);

export const IngestRun = z
  .strictObject({
    run_id: z.string().min(1).max(LIMITS.idMaxChars),
    data_source: DataSource,
    started_at: IsoDateTime,
    finished_at: IsoDateTime,
    stage_seconds: z.strictObject({
      download: seconds,
      parse: seconds,
      chunk: seconds,
      embed: seconds,
      index: seconds,
    }),
    counts: z.strictObject({
      seen: Count,
      new: Count,
      changed: Count,
      unchanged_skipped: Count,
      failed: Count,
    }),
    embedder_model: z.string().min(1).max(LIMITS.modelNameMaxChars).describe("e.g. BAAI/bge-small-en-v1.5"),
    embedding_dim: z.number().int().min(1).describe("vector dimension of that model"),
  })
  .meta({ id: "IngestRun", description: "Summary of one ingest pass (element of GET /ingest-runs)" });

export type IngestRun = z.infer<typeof IngestRun>;
