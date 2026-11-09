import { z } from "zod";
import { CHAMBERS, Count, DocId, InadmissibilityGround, IsoDate, Outcome } from "../shared";
import { CaseName, DocTypeWithLabel, HudocUrl, MCP_LIMITS, McpCorpus } from "./shared";

/** The validated parameter template behind count_cases (mirrors rag.answer.stats.sanitize_params). */
const countParamsShape = {
  group_by: z
    .enum(["none", "reason", "article", "outcome", "year", "doc_type"])
    .describe(
      "'none' = just a count; 'reason' = why applications were inadmissible; 'article' = which Convention articles; 'outcome' = breakdown by result; 'year' = per year; 'doc_type' = per document type",
    ),
  topic: z
    .enum(["deportation"])
    .nullable()
    .describe("'deportation' = deportation, expulsion, removal or extradition cases (defined in the result)"),
  keywords: z
    .array(z.string().regex(/^[a-z][a-z -]{2,30}$/))
    .max(4)
    .describe("other subject words the text must contain (lower case); usually empty; never 'uk' (every case is a UK case)"),
  articles: z
    .array(z.string().regex(/^(?:P\d+-)?\d{1,2}$/))
    .max(5)
    .describe("Convention articles, e.g. ['3', '8', 'P1-1']"),
  doc_types: z
    .array(z.enum(["judgment", "decision", "communicated", "legal_summary"]))
    .max(4)
    .describe("default (empty) = judgments, decisions and communicated cases; legal summaries would double count"),
  outcomes: z
    .array(z.enum(["violation", "no_violation", "mixed", "inadmissible", "partly_inadmissible", "struck_out", "admissible"]))
    .max(7)
    .describe(
      "'found a violation' / 'at least one violation' = ['violation', 'mixed']; 'declared inadmissible' = ['inadmissible'] (add 'partly_inadmissible' only for 'in whole or in part')",
    ),
  chambers: z
    .array(z.enum(CHAMBERS))
    .max(3)
    .describe("'Grand Chamber', 'Chamber' (the ordinary Chamber, not the Grand Chamber) or 'Committee'"),
  grounds: z.array(InadmissibilityGround).max(12).describe("only decisions resting on these inadmissibility grounds"),
  count_of: z
    .enum(["total", "top_group", "total_and_subset"])
    .describe(
      "'total' = matching documents; 'top_group' = documents in the most common group (needs group_by); 'total_and_subset' = 'how many X, and how many of them Y': the total without the outcome filter AND the subset with it",
    ),
  date_from: IsoDate.nullable().describe("first date included, YYYY-MM-DD"),
  date_to: IsoDate.nullable().describe("last date included, YYYY-MM-DD"),
};

export const McpCountCasesInput = z
  .strictObject(
    Object.fromEntries(Object.entries(countParamsShape).map(([k, v]) => [k, v.optional()])) as {
      [K in keyof typeof countParamsShape]: z.ZodOptional<(typeof countParamsShape)[K]>;
    },
  )
  .meta({ id: "McpCountCasesInput", description: "count_cases arguments: a fixed, validated template (no SQL)" });

const cell = z.union([z.string().max(MCP_LIMITS.countCellMaxChars), z.number(), z.boolean(), z.null()]);

export const McpCountCasesResult = z
  .strictObject({
    answer: z
      .string()
      .max(MCP_LIMITS.plainTextMaxChars)
      .describe("every number asked for, in a plain sentence naming every filter"),
    count: Count.describe("the number asked for: matching documents, or the documents in the top group"),
    scope_total: Count.nullable().describe("count_of 'total_and_subset': documents in scope before the outcome filter (count is the subset); otherwise null"),
    top_group: z
      .strictObject({ key: z.string().max(60), label: z.string().max(120), count: Count })
      .nullable()
      .describe("count_of 'top_group': the most common group; otherwise null"),
    filters: z.string().max(600).describe("the set counted, in plain words"),
    definitions: z
      .array(z.string().max(MCP_LIMITS.definitionMaxChars))
      .max(MCP_LIMITS.definitionsMax)
      .describe("definitions used, e.g. what 'found a violation' and 'deportation case' mean here"),
    sql: z.string().max(MCP_LIMITS.sqlMaxChars).describe("the exact read-only SQL that was run"),
    columns: z.array(z.string().max(40)).max(MCP_LIMITS.countColumnsMax),
    rows: z.array(z.array(cell).max(MCP_LIMITS.countColumnsMax)).max(MCP_LIMITS.countRowsMax),
    matching_cases: z
      .array(
        z.strictObject({
          doc_id: DocId,
          case_name: CaseName,
          ...DocTypeWithLabel,
          date: IsoDate,
          outcome: Outcome,
          hudoc_url: HudocUrl,
        }),
      )
      .max(MCP_LIMITS.countCasesMax)
      .describe("up to 20 counted documents, most recent first; examples only: the SQL is the evidence for the count"),
    params: z.strictObject(countParamsShape).describe("the template parameters actually used, after validation and defaults"),
    corpus: McpCorpus,
  })
  .meta({ id: "McpCountCasesResult", description: "count_cases result: numbers from SQL over the corpus metadata" });

export type McpCountCasesInput = z.infer<typeof McpCountCasesInput>;
export type McpCountCasesResult = z.infer<typeof McpCountCasesResult>;
