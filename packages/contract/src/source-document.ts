import { z } from "zod";
import { LIMITS } from "./limits";
import { CHAMBERS, DataSource, DocId, DocType, InadmissibilityGround, IsoDate, Outcome } from "./shared";

const sourceDocumentShape = {
  item_id: DocId.describe("HUDOC item id, e.g. 001-57619; legislation uses echr-convention / ukpga-1998-42"),
  case_name: z.string().min(1).max(300).describe("HUDOC docname without the 'CASE OF ' prefix"),
  application_numbers: z.array(z.string().max(40)).max(LIMITS.applicationNumbersMax).describe("e.g. ['14038/88']; empty for legislation"),
  ecli: z.string().nullable().describe("ECLI if HUDOC has one (older documents: null)"),
  doc_type: DocType,
  chamber: z.enum(CHAMBERS).nullable().describe("null for communicated cases and legislation"),
  date: IsoDate.describe("judgment / decision / summary date (HUDOC kpdate); legislation: signature or Royal Assent date"),
  articles: z.array(z.string().max(20)).max(LIMITS.articlesPerDocMax).describe("HUDOC article codes: '3', '8-1', 'P1-3', '35-3-a'"),
  outcome_raw: z.string().max(LIMITS.outcomeRawMaxChars).nullable().describe("HUDOC `conclusion` verbatim"),
  outcome: Outcome.describe("normalised outcome; see shared.ts"),
  inadmissibility_grounds: z
    .array(InadmissibilityGround)
    .max(12)
    .nullable()
    .describe(
      "why (part of) the application was declared inadmissible; null = not applicable (no inadmissibility) or not extracted yet",
    ),
  inadmissibility_grounds_source: z
    .enum(["metadata", "text"])
    .nullable()
    .describe("metadata = stated in HUDOC `conclusion`; text = extracted from the decision text; null iff grounds are null"),
  importance: z.number().int().min(1).max(4).nullable().describe("HUDOC importance: 1 = key case ... 4 = low"),
  language: z.enum(["en", "fr"]),
  source_url: z.url(),
  sha256: z.string().regex(/^[0-9a-f]{64}$/).describe("sha256 of the stored file"),
  data_source: DataSource,
};

export const SourceDocument = z
  .strictObject(sourceDocumentShape)
  .meta({ id: "SourceDocument", description: "One ingested document (case, decision, summary or legislation)" });

/** One line of data/snapshot/manifest.json: a SourceDocument plus where the stored file lives. */
export const ManifestEntry = z
  .strictObject({
    ...sourceDocumentShape,
    retrieved_at: z.iso.datetime(),
    format: z.enum(["html", "docx", "pdf", "xml", "txt"]),
    path: z.string().describe("relative to data/snapshot/, e.g. hudoc/001-57619.html"),
  })
  .meta({ id: "ManifestEntry", description: "SourceDocument + retrieval details; element type of data/snapshot/manifest.json" });

export type SourceDocument = z.infer<typeof SourceDocument>;
export type ManifestEntry = z.infer<typeof ManifestEntry>;
