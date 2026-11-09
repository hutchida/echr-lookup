import { z } from "zod";
import { LIMITS } from "./limits";
import { Citation, StatsQueryResult } from "./stats";
import { ChunkStrategy, Count, ParagraphId, SearchMode } from "./shared";

export const ClaimStatus = z.enum(["supported", "unsupported", "unverified"]);
export const AnswerRoute = z.enum(["rag", "stats"]);

export const Claim = z.strictObject({
  id: z.string().min(1).max(16),
  text: z.string().min(1).max(LIMITS.claimTextMaxChars),
  citation_ids: z.array(ParagraphId).max(LIMITS.claimCitationIdsMax),
  status: ClaimStatus,
  reason: z.string().max(LIMITS.claimReasonMaxChars).describe("short reason for the verification status"),
  role: z
    .enum(["short_answer", "point"])
    .optional()
    .describe('absent means "point"; at most one "short_answer", and it is the first claim'),
  group: z
    .string()
    .max(80)
    .optional()
    .describe("short neutral heading shared by consecutive points, e.g. \"Where the Court allowed the deportation\""),
});

export const StepCost = z.strictObject({
  step: z.enum(["route", "retrieve", "rerank", "generate", "verify"]),
  model: z.string().min(1).max(LIMITS.modelNameMaxChars).nullable().describe("null for non-model steps such as retrieve"),
  tokens_in: Count,
  tokens_out: Count,
  tokens_cached: Count,
  cost_usd: z.number().min(0),
  latency_ms: z.number().min(0),
});

export const AnswerRequest = z
  .strictObject({
    question: z.string().min(1).max(LIMITS.questionMaxChars),
    options: z
      .strictObject({
        chunking: ChunkStrategy.optional(),
        mode: SearchMode.optional(),
        k: z.number().int().min(1).max(LIMITS.searchMaxHits).optional(),
        route: z.enum(["auto", "rag", "stats"]).optional().describe("auto = let the router decide"),
      })
      .optional(),
  })
  .meta({ id: "AnswerRequest", description: "POST /ask body" });

export const Answer = z
  .strictObject({
    request_id: z.string().min(1).max(LIMITS.requestIdMaxChars),
    question: z.string().max(LIMITS.questionMaxChars),
    route: AnswerRoute,
    answer_text: z.string().max(LIMITS.answerTextMaxChars),
    claims: z.array(Claim).max(LIMITS.claimsMax),
    citations: z.array(Citation).max(LIMITS.citationsMax),
    stats: StatsQueryResult.nullable().describe("set only when route = stats"),
    refused_or_not_in_sources: z.boolean().describe("true when the sources do not answer the question"),
    steps: z.array(StepCost).max(LIMITS.stepsMax),
    total_cost_usd: z.number().min(0),
    total_latency_ms: z.number().min(0),
    models_used: z.array(z.string().max(LIMITS.modelNameMaxChars)).max(LIMITS.modelsMax),
  })
  .meta({ id: "Answer", description: "POST /ask response (payload < 50 KB)" });

export type AnswerRequest = z.infer<typeof AnswerRequest>;
export type Answer = z.infer<typeof Answer>;
