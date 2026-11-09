import { z } from "zod";
import { Count, DataSource, DocType } from "../shared";

/** Size and count limits for MCP tool results (Gate 0 prep for the MCP slice). */
export const MCP_LIMITS = {
  /** Every tool result, serialised as compact JSON (UTF-8), stays at or under this many bytes. */
  resultMaxBytes: 25_000,
  searchMaxHits: 10,
  searchDefaultHits: 8,
  quoteMaxChars: 600,
  citeMaxChars: 200,
  paraLabelMaxChars: 50,
  /** A HUDOC page URL plus a `#:~:text=` fragment of at most 8 words (see text_fragment in py/echr_mcp/common.py). */
  hudocUrlMaxChars: 400,
  caseNameMaxChars: 200,
  articlesMax: 60,
  paragraphIdsMax: 10,
  neighboursMax: 2,
  /** 10 requested paragraphs, each with up to 2 neighbours on each side. */
  paragraphsMax: 50,
  paragraphTextMaxChars: 20_000,
  operativeMax: 30,
  operativeTextMaxChars: 1500,
  outlineMax: 12,
  countCasesMax: 20,
  countRowsMax: 20,
  countColumnsMax: 6,
  countCellMaxChars: 80,
  sqlMaxChars: 4000,
  definitionsMax: 10,
  definitionMaxChars: 400,
  checkQuoteMaxChars: 2000,
  plainTextMaxChars: 1000,
} as const;

export const DOC_TYPE_LABELS = {
  judgment: "Judgment",
  decision: "Decision",
  communicated: "Communicated case",
  legal_summary: "Legal summary",
  legislation: "Legislation",
} as const;
export const DocTypeLabel = z
  .enum(["Judgment", "Decision", "Communicated case", "Legal summary", "Legislation"])
  .describe("plain label for doc_type; a Legal summary is the Court's digest, not the judgment itself");

export const CaseName = z
  .string()
  .min(1)
  .max(MCP_LIMITS.caseNameMaxChars)
  .describe("display name, e.g. 'Chahal v. the United Kingdom' (HUDOC's upper-case names are title-cased)");

export const ParaLabel = z
  .string()
  .min(1)
  .max(MCP_LIMITS.paraLabelMaxChars)
  .describe(
    "readable name of the paragraph, for display and citing: '§79' for a numbered paragraph; 'Law, para 2' for an unnumbered one (n counts within that section of the document, in order); 'Article 8' for legislation. The stable id is paragraph_id",
  );

export const Cite = z
  .string()
  .max(MCP_LIMITS.citeMaxChars)
  .describe(
    "ready-to-paste citation '[<case name>, <doc type label>, <para_label>]', e.g. '[Chahal v. the United Kingdom, Judgment, §79]' or '[Harkins and Edwards v. the United Kingdom, Legal summary, Law, para 2]'. Copy it verbatim after the claim it supports; when two paragraphs of one result would share a string, the doc id is added to the doc type, e.g. 'Judgment (001-58004)'",
  );

export const HudocUrl = z
  .url()
  .max(MCP_LIMITS.hudocUrlMaxChars)
  .describe(
    "the document's public page (HUDOC; legislation: its official source). Where the result has a quote or text, it ends '#:~:text=<its first 6-8 words, percent-encoded>': a browser that supports text fragments opens the page and highlights those words. A case-level link with no quote has no fragment",
  );

/** Every tool result carries this, so the host model can say what the corpus covers. */
export const McpCorpus = z
  .strictObject({
    documents: Count.describe("documents loaded for this data_source"),
    data_source: DataSource,
    scope: z.string().max(200).describe("e.g. 'UK cases only (plus the Convention and the Human Rights Act 1998)'"),
    sample_note: z
      .string()
      .max(300)
      .nullable()
      .describe("snapshot mode: 'Small committed sample, not the full HUDOC download.'; full mode: null"),
  })
  .describe("what the corpus covers: 'not found here' does not mean the Court never decided it");

export const DocTypeWithLabel = { doc_type: DocType, doc_type_label: DocTypeLabel };
