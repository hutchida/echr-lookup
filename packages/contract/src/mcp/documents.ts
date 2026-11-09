import { z } from "zod";
import { CHAMBERS, Count, DocId, InadmissibilityGround, IsoDate, Outcome, ParagraphId, Section } from "../shared";
import { CaseName, Cite, DocTypeWithLabel, HudocUrl, MCP_LIMITS, McpCorpus, ParaLabel } from "./shared";

// ---------------------------------------------------------------------------------------------
// get_paragraphs
// ---------------------------------------------------------------------------------------------

export const McpGetParagraphsInput = z
  .strictObject({
    paragraph_ids: z
      .array(ParagraphId)
      .min(1)
      .max(MCP_LIMITS.paragraphIdsMax)
      .describe("paragraph ids from search_case_law or get_case, e.g. ['001-58004§79']"),
    neighbours: z
      .number()
      .int()
      .min(0)
      .max(MCP_LIMITS.neighboursMax)
      .optional()
      .describe("also return this many paragraphs before and after each one (default 0, max 2)"),
  })
  .meta({ id: "McpGetParagraphsInput", description: "get_paragraphs arguments" });

export const McpParagraph = z.strictObject({
  paragraph_id: ParagraphId,
  para_label: ParaLabel,
  doc_id: DocId,
  case_name: CaseName,
  ...DocTypeWithLabel,
  number: z.number().int().min(1).nullable().describe("paragraph number as printed; null for operative/unnumbered items"),
  section: Section,
  text: z.string().min(1).max(MCP_LIMITS.paragraphTextMaxChars),
  truncated: z.boolean().describe("true = text was cut (ends with '…') to keep the result under 25 KB; request it alone for the full text"),
  requested: z.boolean().describe("true = you asked for it; false = a neighbour"),
  hudoc_url: HudocUrl,
  cite: Cite,
});

export const McpGetParagraphsResult = z
  .strictObject({
    paragraphs: z
      .array(McpParagraph)
      .max(MCP_LIMITS.paragraphsMax)
      .describe("grouped by document, in document order; each paragraph once"),
    not_found: z.array(z.string().max(64)).max(MCP_LIMITS.paragraphIdsMax).describe("requested ids not in this corpus"),
    corpus: McpCorpus,
  })
  .meta({ id: "McpGetParagraphsResult", description: "get_paragraphs result: full text with section labels" });

// ---------------------------------------------------------------------------------------------
// get_case
// ---------------------------------------------------------------------------------------------

export const McpGetCaseInput = z
  .strictObject({
    case_id: DocId.describe("document id, e.g. '001-58004' (the part of a paragraph_id before '§')"),
  })
  .meta({ id: "McpGetCaseInput", description: "get_case arguments" });

export const McpOutlineSection = z.strictObject({
  section: Section,
  first_paragraph_id: ParagraphId,
  last_paragraph_id: ParagraphId,
  paragraph_count: Count,
});

export const McpGetCaseResult = z
  .strictObject({
    doc_id: DocId,
    case_name: CaseName,
    ...DocTypeWithLabel,
    date: IsoDate,
    chamber: z.enum(CHAMBERS).nullable(),
    application_numbers: z.array(z.string().max(40)).max(20),
    articles: z.array(z.string().max(20)).max(MCP_LIMITS.articlesMax),
    importance: z.number().int().min(1).max(4).nullable().describe("HUDOC importance: 1 = key case … 4 = low"),
    outcome: Outcome,
    outcome_label: z.string().max(200).describe("the normalised outcome in plain words"),
    outcome_raw: z.string().max(2000).nullable().describe("HUDOC's conclusion text (cut at 2000 characters)"),
    inadmissibility_grounds: z.array(InadmissibilityGround).max(12).nullable(),
    hudoc_url: HudocUrl,
    paragraph_count: Count,
    operative_provisions: z
      .array(
        z.strictObject({
          paragraph_id: ParagraphId,
          para_label: ParaLabel,
          text: z.string().min(1).max(MCP_LIMITS.operativeTextMaxChars),
          cite: Cite,
        }),
      )
      .max(MCP_LIMITS.operativeMax)
      .describe("what the Court decided, item by item, in order; empty for documents without them"),
    outline: z
      .array(McpOutlineSection)
      .max(MCP_LIMITS.outlineMax)
      .describe("consecutive runs of paragraphs by section, in document order"),
    corpus: McpCorpus,
  })
  .meta({ id: "McpGetCaseResult", description: "get_case result: metadata, outcome, operative provisions, outline" });

export type McpGetParagraphsResult = z.infer<typeof McpGetParagraphsResult>;
export type McpGetCaseResult = z.infer<typeof McpGetCaseResult>;
