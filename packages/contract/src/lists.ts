import { z } from "zod";
import { EvalRunSummary } from "./eval";
import { IngestRun } from "./ingest-run";
import { LIMITS } from "./limits";

export const IngestRunList = z
  .strictObject({
    runs: z.array(IngestRun).max(LIMITS.listRunsMax).describe("newest first"),
  })
  .meta({ id: "IngestRunList", description: "GET /ingest-runs response (at most 50 runs, newest first)" });

export const EvalRunList = z
  .strictObject({
    runs: z.array(EvalRunSummary).max(LIMITS.listRunsMax).describe("newest first; fetch one with GET /eval-runs/{id}"),
  })
  .meta({ id: "EvalRunList", description: "GET /eval-runs response (at most 50 summaries, newest first)" });

export type IngestRunList = z.infer<typeof IngestRunList>;
export type EvalRunList = z.infer<typeof EvalRunList>;
