import { z } from "zod";
import { DocId, DocType, IsoDate, Outcome, ParagraphId, Section } from "../shared";
import { CaseName, Cite, DocTypeWithLabel, HudocUrl, MCP_LIMITS, McpCorpus, ParaLabel } from "./shared";

const year = z.number().int().min(1950).max(2100);

export const McpSearchCaseLawInput = z
  .strictObject({
    query: z
      .string()
      .min(1)
      .max(500)
      .describe("what to look for, in plain words, e.g. 'deportation of a settled migrant with a criminal record, family life'"),
    article: z
      .string()
      .max(20)
      .regex(/^(?:P\d+-)?\d{1,2}(?:-[0-9a-z]+)*$/)
      .optional()
      .describe("Convention article, HUDOC style: '3', '8', 'P1-1'; matches sub-paragraphs too ('8' matches '8-1')"),
    doc_type: DocType.optional().describe("only this document type"),
    outcome: Outcome.optional().describe("only documents with this normalised outcome ('mixed' = at least one violation and one no-violation finding)"),
    year_from: year.optional().describe("first year included"),
    year_to: year.optional().describe("last year included"),
    limit: z
      .number()
      .int()
      .min(1)
      .max(MCP_LIMITS.searchMaxHits)
      .optional()
      .describe(`number of paragraphs to return (default ${MCP_LIMITS.searchDefaultHits}, max ${MCP_LIMITS.searchMaxHits})`),
  })
  .meta({ id: "McpSearchCaseLawInput", description: "search_case_law arguments" });

export const McpSearchHit = z.strictObject({
  rank: z.number().int().min(1),
  paragraph_id: ParagraphId.describe("the paragraph to cite, '<doc_id>§<ref>'"),
  para_label: ParaLabel,
  doc_id: DocId,
  case_name: CaseName,
  ...DocTypeWithLabel,
  date: IsoDate,
  outcome: Outcome,
  articles: z.array(z.string().max(20)).max(MCP_LIMITS.articlesMax),
  section: Section,
  quote: z
    .string()
    .min(1)
    .max(MCP_LIMITS.quoteMaxChars)
    .describe(
      "verbatim text of the paragraph that contains the best-matching sentence, starting and ending at sentence boundaries; a leading or trailing '…' marks a cut. Quote only from here (or get_paragraphs), and check anything else with check_quote. hudoc_url's text fragment is this quote's first words",
    ),
  hudoc_url: HudocUrl,
  cite: Cite,
});

export const McpSearchCaseLawResult = z
  .strictObject({
    query: z.string().max(500),
    filters: z.string().max(300).describe("the filters applied, in plain words; '' when none"),
    hits: z
      .array(McpSearchHit)
      .max(MCP_LIMITS.searchMaxHits)
      .describe("best first; one paragraph per hit, no duplicates; empty when nothing matched"),
    corpus: McpCorpus,
  })
  .meta({ id: "McpSearchCaseLawResult", description: "search_case_law result: hybrid BM25 + vector search, reranked" });

export type McpSearchCaseLawInput = z.infer<typeof McpSearchCaseLawInput>;
export type McpSearchCaseLawResult = z.infer<typeof McpSearchCaseLawResult>;
