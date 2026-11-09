import { z } from "zod";
import { Chunk } from "./chunk";
import { LIMITS } from "./limits";
import { ChunkStrategy, DocType, IsoDate, Outcome, ParagraphId, SearchMode } from "./shared";

const rank = z.number().int().min(1).nullable();
const score = z.number().nullable();

export const SearchFilters = z.strictObject({
  article: z.string().optional().describe("HUDOC article code, e.g. '3' or 'P1-3'"),
  doc_types: z.array(DocType).optional(),
  outcomes: z.array(Outcome).optional(),
  date_from: IsoDate.optional(),
  date_to: IsoDate.optional(),
});

export const SearchRequest = z
  .strictObject({
    query: z.string().min(1).max(LIMITS.questionMaxChars),
    mode: SearchMode,
    chunking: ChunkStrategy,
    k: z.number().int().min(1).max(LIMITS.searchMaxHits),
    filters: SearchFilters.optional(),
  })
  .meta({ id: "SearchRequest", description: "POST /search body" });

export const SearchHit = z.strictObject({
  rank: z.number().int().min(1).describe("final position in this result list"),
  case_name: z.string(),
  chunk: Chunk,
  paragraph_ids: z
    .array(ParagraphId)
    .min(1)
    .describe("paragraphs to cite for this hit: non-empty subset of chunk.paragraph_ids"),
  scores: z
    .strictObject({
      bm25_score: score,
      bm25_rank: rank,
      vector_score: score,
      vector_rank: rank,
      rrf_score: score,
      rrf_rank: rank,
      rerank_score: score,
      rerank_rank: rank,
    })
    .describe("per-method score and rank; null when that method did not run"),
});

export const SearchResult = z
  .strictObject({
    query: z.string(),
    mode: SearchMode,
    chunking: ChunkStrategy,
    k: z.number().int().min(1).max(LIMITS.searchMaxHits),
    hits: z.array(SearchHit).max(LIMITS.searchMaxHits),
    timings_ms: z.strictObject({
      bm25: z.number().min(0).nullable(),
      vector: z.number().min(0).nullable(),
      fuse: z.number().min(0).nullable(),
      rerank: z.number().min(0).nullable(),
      total: z.number().min(0),
    }),
  })
  .meta({ id: "SearchResult", description: "POST /search response (at most 50 hits)" });

export type SearchRequest = z.infer<typeof SearchRequest>;
export type SearchResult = z.infer<typeof SearchResult>;
