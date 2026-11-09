import { z } from "zod";
import { CostLogEntry, CostPurpose } from "./cost-log";
import { LIMITS } from "./limits";
import { Count, IsoDateTime } from "./shared";

const usage = {
  calls: Count,
  tokens_in: Count,
  tokens_out: Count,
  tokens_cached: Count,
  cost_usd: z.number().min(0),
};

export const CostSummary = z
  .strictObject({
    total_usd: z.number().min(0),
    since: IsoDateTime.nullable().describe("timestamp of the earliest cost_log entry counted; null when there are none"),
    by_purpose: z
      .array(z.strictObject({ purpose: CostPurpose, ...usage }))
      .max(LIMITS.costByPurposeMax),
    by_model: z
      .array(z.strictObject({ model: z.string().min(1).max(LIMITS.modelNameMaxChars), ...usage }))
      .max(LIMITS.costByModelMax),
    recent: z.array(CostLogEntry).max(LIMITS.costRecentMax).describe("most recent entries first"),
  })
  .meta({ id: "CostSummary", description: "GET /costs response; also embedded in CorpusStats.costs" });

export type CostSummary = z.infer<typeof CostSummary>;
