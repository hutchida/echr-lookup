import { z } from "zod";
import { LIMITS } from "./limits";
import { Count, IsoDateTime } from "./shared";

export const CostPurpose = z.enum(["embed", "generate", "verify", "route", "judge", "rerank"]);

export const CostLogEntry = z
  .strictObject({
    id: z.string().min(1).max(LIMITS.idMaxChars),
    timestamp: IsoDateTime,
    model: z.string().min(1).max(LIMITS.modelNameMaxChars),
    purpose: CostPurpose,
    tokens_in: Count,
    tokens_out: Count,
    tokens_cached: Count,
    cost_usd: z.number().min(0),
    latency_ms: z.number().min(0),
    request_id: z.string().min(1).max(LIMITS.idMaxChars),
  })
  .meta({ id: "CostLogEntry", description: "One model call, as stored in the cost_log table (element of GET /costs `recent`)" });

export type CostLogEntry = z.infer<typeof CostLogEntry>;
