import { z } from "zod";
import { Count, DocType, Outcome, ParagraphId } from "../shared";
import { Cite, DocTypeLabel, MCP_LIMITS, McpCorpus, ParaLabel } from "./shared";

// ---------------------------------------------------------------------------------------------
// corpus_info
// ---------------------------------------------------------------------------------------------

export const McpCorpusInfoInput = z.strictObject({}).meta({ id: "McpCorpusInfoInput", description: "corpus_info takes no arguments" });

export const McpCorpusInfoResult = z
  .strictObject({
    corpus: McpCorpus,
    totals: z.strictObject({ documents: Count, paragraphs: Count }),
    by_doc_type: z.array(z.strictObject({ key: DocType, label: DocTypeLabel, count: Count })).max(5),
    by_outcome: z
      .array(z.strictObject({ key: Outcome, label: z.string().max(200), count: Count }))
      .max(9)
      .describe("normalised outcome; label explains it in plain words"),
    by_article: z
      .array(z.strictObject({ key: z.string().max(20), count: Count }))
      .max(25)
      .describe("top Convention articles by number of documents, most frequent first (8-1 counts as 8)"),
    year_range: z.strictObject({ from: z.number().int(), to: z.number().int() }),
    missing: z
      .array(
        z.strictObject({
          what: z.string().max(200),
          count: Count.nullable().describe("how many, when known"),
          why: z.string().max(400),
        }),
      )
      .max(8)
      .describe("what is NOT in the corpus and why (e.g. scanned decisions with no text, Commission reports)"),
  })
  .meta({ id: "McpCorpusInfoResult", description: "corpus_info result: what the corpus covers and what it lacks" });

// ---------------------------------------------------------------------------------------------
// check_quote
// ---------------------------------------------------------------------------------------------

export const McpCheckQuoteInput = z
  .strictObject({
    paragraph_id: ParagraphId,
    quote: z.string().min(1).max(MCP_LIMITS.checkQuoteMaxChars).describe("the text you intend to quote from that paragraph"),
  })
  .meta({ id: "McpCheckQuoteInput", description: "check_quote arguments" });

export const McpCheckQuoteResult = z
  .strictObject({
    paragraph_id: z.string().max(64),
    paragraph_found: z.boolean(),
    verbatim: z
      .boolean()
      .describe(
        "true = the quote appears in the paragraph word for word, ignoring only whitespace differences, curly vs straight quotes and dashes, and '…' marking an omission",
      ),
    closest_match: z
      .string()
      .max(MCP_LIMITS.quoteMaxChars)
      .nullable()
      .describe("the paragraph's most similar passage (verbatim from the paragraph); null when the paragraph is not found"),
    similarity: z.number().min(0).max(1).describe("1 = identical after normalisation"),
    para_label: ParaLabel.nullable().describe("the paragraph's readable label; null when the paragraph is not found"),
    cite: Cite.nullable(),
    corpus: McpCorpus,
  })
  .meta({ id: "McpCheckQuoteResult", description: "check_quote result: deterministic, no model involved" });

export type McpCorpusInfoResult = z.infer<typeof McpCorpusInfoResult>;
export type McpCheckQuoteResult = z.infer<typeof McpCheckQuoteResult>;
