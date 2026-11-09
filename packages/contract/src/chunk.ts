import { z } from "zod";
import { ChunkStrategy, Count, DocId, ParagraphId } from "./shared";

export const Chunk = z
  .strictObject({
    id: z.string().min(1).describe("<doc-id>:<strategy>:<index>, e.g. 001-57619:recursive:41"),
    doc_id: DocId,
    strategy: ChunkStrategy,
    text: z.string().min(1),
    paragraph_ids: z.array(ParagraphId).min(1).describe("paragraphs this chunk covers, in order"),
    token_count: Count.describe("tokens by the embedder's tokenizer"),
  })
  .meta({ id: "Chunk", description: "A retrievable passage" });

export type Chunk = z.infer<typeof Chunk>;
