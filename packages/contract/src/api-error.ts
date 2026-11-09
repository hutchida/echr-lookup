import { z } from "zod";
import { LIMITS } from "./limits";

export const ApiError = z
  .strictObject({
    error: z.string().min(1).max(LIMITS.errorTextMaxChars).describe("short machine-friendly message, e.g. 'not_found'"),
    detail: z.string().max(LIMITS.errorTextMaxChars).nullable().describe("human-readable explanation"),
    request_id: z.string().max(LIMITS.requestIdMaxChars).nullable().describe("matches Answer.request_id / cost_log.request_id when known"),
  })
  .meta({ id: "ApiError", description: "Error body returned by every endpoint on a non-2xx status" });

export type ApiError = z.infer<typeof ApiError>;
