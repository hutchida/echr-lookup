import { z } from "zod";
import { LIMITS } from "./limits";
import { ParagraphId, DocId, DocType } from "./shared";

export const Citation = z.strictObject({
  paragraph_id: ParagraphId,
  doc_id: DocId,
  case_name: z.string().max(LIMITS.caseNameMaxChars),
  doc_type: DocType.describe("type of the cited paragraph's document, so a legal summary is never mistaken for the judgment"),
  quote: z.string().max(LIMITS.quoteMaxChars).describe("verbatim snippet from that paragraph"),
  link_target: z.string().max(LIMITS.linkMaxChars).describe("URL or app route that opens the paragraph"),
});

/** A case counted by a stats query. Its quote only illustrates the case: the SQL is the evidence for the count. */
export const MatchingCase = z.strictObject({
  doc_id: DocId,
  case_name: z.string().max(LIMITS.caseNameMaxChars),
  doc_type: DocType,
  paragraph_id: ParagraphId.nullable().describe(
    "the quoted paragraph; null when no paragraph honestly illustrates the filter (e.g. no operative clause states the violation)",
  ),
  quote: z.string().max(LIMITS.quoteMaxChars).describe("verbatim snippet from that paragraph; empty when paragraph_id is null"),
  link_target: z
    .string()
    .max(LIMITS.linkMaxChars)
    .describe("/case/<doc_id>#p<ref>, or /case/<doc_id> when no paragraph is quoted"),
});

export const StatsQueryResult = z
  .strictObject({
    question: z.string().max(LIMITS.questionMaxChars),
    sql: z.string().max(LIMITS.sqlMaxChars).describe("the read-only SQL that produced the rows"),
    columns: z.array(z.string()).max(LIMITS.statsColumnsMax),
    rows: z
      .array(z.array(z.union([z.string().max(LIMITS.statsCellMaxChars), z.number(), z.boolean(), z.null()])))
      .max(LIMITS.statsRowsMax),
    matching_cases: z.array(MatchingCase).max(LIMITS.matchingCasesMax),
    count: z.number().int().min(0).describe("number of matching documents (can exceed rows shown)"),
    scope_total: z
      .number()
      .int()
      .min(0)
      .nullable()
      .describe(
        "when the question asks for a total AND how many of those have an outcome: the documents in the scope before the outcome filter (count is the subset); otherwise null",
      ),
    explanation: z.string().max(LIMITS.explanationMaxChars),
  })
  .meta({ id: "StatsQueryResult", description: "Counting-question result, from SQL over metadata. Returned inside Answer.stats by POST /ask (route = stats)" });

export type Citation = z.infer<typeof Citation>;
export type MatchingCase = z.infer<typeof MatchingCase>;
export type StatsQueryResult = z.infer<typeof StatsQueryResult>;
