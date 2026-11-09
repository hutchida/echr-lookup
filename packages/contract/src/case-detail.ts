import { z } from "zod";
import { LIMITS } from "./limits";
import { Paragraph } from "./paragraph";
import { SourceDocument } from "./source-document";

export const CaseDetail = z
  .strictObject({
    document: SourceDocument,
    paragraphs: z
      .array(Paragraph)
      .max(LIMITS.caseParagraphsMax)
      .describe("every paragraph of the document, in document order; the case viewer anchors and highlights § ids"),
  })
  .meta({ id: "CaseDetail", description: "GET /case/{id} response: the document and all its paragraphs" });

export type CaseDetail = z.infer<typeof CaseDetail>;
