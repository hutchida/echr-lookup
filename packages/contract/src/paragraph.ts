import { z } from "zod";
import { LIMITS } from "./limits";
import { DocId, ParagraphId, Section } from "./shared";

export const Paragraph = z
  .strictObject({
    id: ParagraphId.describe("<doc-id>§<ref>, e.g. 001-57619§88"),
    doc_id: DocId,
    number: z.number().int().min(1).nullable().describe("paragraph number as printed; null for op/unnumbered items"),
    section: Section,
    text: z.string().min(1).max(LIMITS.paragraphTextMaxChars),
  })
  .meta({ id: "Paragraph", description: "One citable paragraph of a document (element of GET /case/{id})" });

export type Paragraph = z.infer<typeof Paragraph>;
