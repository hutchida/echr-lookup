import { ChunkStrategy as ChunkStrategySchema, DOC_TYPES, LIMITS } from "@echr/contract";
import type { DocType as DocTypeSchema, SearchRequest, SearchResult } from "@echr/contract";

export type ChunkStrategy = (typeof ChunkStrategySchema)["options"][number];
export type DocType = (typeof DocTypeSchema)["options"][number];
export const CHUNK_STRATEGIES = ChunkStrategySchema.options;

export type SearchHit = SearchResult["hits"][number];
export type LabMode = "bm25" | "vector" | "hybrid" | "hybrid_rerank";
export type ColumnKey = "bm25" | "vector" | "fused" | "reranked";

export const DEMO_QUERY = "Does the Convention stop the UK deporting criminals?";
export const DEFAULT_CHUNKING: ChunkStrategy = "recursive";
export const DEFAULT_K = 10;

export const COLUMNS: {
  key: ColumnKey;
  mode: LabMode;
  title: string;
  scoreLabel: string;
  explain: string;
}[] = [
  {
    key: "bm25",
    mode: "bm25",
    title: "BM25 (keyword)",
    scoreLabel: "BM25 score",
    explain:
      "Matches the exact words, counting rare ones (like Soering) for more. Great for names and phrases, blind to synonyms: “deport” does not match “expulsion”.",
  },
  {
    key: "vector",
    mode: "vector",
    title: "Vector (meaning)",
    scoreLabel: "cosine similarity",
    explain:
      "Compares the meaning of the question with each passage using embeddings. Finds paraphrases and related topics, but can drift away from the exact words or names.",
  },
  {
    key: "fused",
    mode: "hybrid",
    title: "Fused (hybrid, RRF)",
    scoreLabel: "RRF score",
    explain:
      "Merges the two lists by rank (Reciprocal Rank Fusion): a passage near the top of both lists wins. No score needs normalising, only the positions matter.",
  },
  {
    key: "reranked",
    mode: "hybrid_rerank",
    title: "Reranked (cross-encoder)",
    scoreLabel: "cross-encoder score",
    explain:
      "A second model reads the question and each fused candidate together and re-scores it. Slower but smarter, so it only sees the top 30 fused passages.",
  },
];

export type LabParams = {
  q: string;
  chunking: ChunkStrategy;
  k: number;
  article: string | null;
  docType: DocType | null;
};

type RawParams = Record<string, string | string[] | undefined>;

const first = (v: string | string[] | undefined): string | undefined => (Array.isArray(v) ? v[0] : v);

/** Turn `/lab?...` search params into safe values; anything missing or invalid falls back to the default. */
export function parseLabParams(raw: RawParams): LabParams {
  const q = (first(raw.q) ?? "").trim().slice(0, LIMITS.questionMaxChars).trim();
  const chunkingRaw = first(raw.chunking);
  const chunking = (CHUNK_STRATEGIES as readonly string[]).includes(chunkingRaw ?? "")
    ? (chunkingRaw as ChunkStrategy)
    : DEFAULT_CHUNKING;
  const kRaw = first(raw.k)?.trim() ?? "";
  const kNum = /^\d+$/.test(kRaw) ? Number(kRaw) : NaN;
  const k = Number.isFinite(kNum) ? Math.min(Math.max(kNum, 1), LIMITS.searchMaxHits) : DEFAULT_K;
  const article = (first(raw.article) ?? "").trim();
  const docTypeRaw = first(raw.doc_type) ?? "";
  return {
    q: q || DEMO_QUERY,
    chunking,
    k,
    article: /^[A-Za-z0-9-]{1,10}$/.test(article) ? article : null,
    docType: (DOC_TYPES as readonly string[]).includes(docTypeRaw) ? (docTypeRaw as DocType) : null,
  };
}

/** The body of the POST /search call for one column. */
export function buildRequest(params: LabParams, mode: LabMode): SearchRequest {
  const filters: NonNullable<SearchRequest["filters"]> = {};
  if (params.article) filters.article = params.article;
  if (params.docType) filters.doc_types = [params.docType];
  return {
    query: params.q,
    mode,
    chunking: params.chunking,
    k: params.k,
    ...(Object.keys(filters).length ? { filters } : {}),
  };
}

/** The shareable `/lab?...` URL for a set of params. */
export function labHref(params: LabParams): string {
  const sp = new URLSearchParams({ q: params.q, chunking: params.chunking, k: String(params.k) });
  if (params.article) sp.set("article", params.article);
  if (params.docType) sp.set("doc_type", params.docType);
  return `/lab?${sp.toString()}`;
}

/** The score that belongs to the column's own method, labelled with what the number is. */
export function scoreOf(key: ColumnKey, hit: SearchHit): { label: string; value: number | null; text: string } {
  const col = COLUMNS.find((c) => c.key === key)!;
  const s = hit.scores;
  const value =
    key === "bm25" ? s.bm25_score : key === "vector" ? s.vector_score : key === "fused" ? s.rrf_score : s.rerank_score;
  const digits = key === "bm25" ? 2 : key === "vector" ? 3 : 4;
  return { label: col.scoreLabel, value, text: value === null ? "n/a" : value.toFixed(digits) };
}

/** Reranking is "off" when the API fell back to plain hybrid: no hit carries a rerank score. */
export function rerankDisabled(result: SearchResult): boolean {
  return result.hits.length > 0 && result.hits.every((h) => h.scores.rerank_score === null);
}

export type Movement =
  | { kind: "up" | "down"; delta: number; from: number; text: string }
  | { kind: "same"; delta: 0; from: number; text: string }
  | { kind: "new"; delta: null; from: number | null; text: string };

/**
 * Where each chunk of `toHits` sat in `fromHits`: moved up / down by n places, unchanged, or "new" when it was
 * not in the earlier list at all. `from` for a new chunk is its fused rank if the hit carries one.
 */
export function rankMovements(fromHits: SearchHit[], toHits: SearchHit[]): Map<string, Movement> {
  const fromRank = new Map(fromHits.map((h) => [h.chunk.id, h.rank]));
  const out = new Map<string, Movement>();
  for (const h of toHits) {
    const before = fromRank.get(h.chunk.id);
    if (before === undefined) {
      const was = h.scores.rrf_rank;
      out.set(h.chunk.id, {
        kind: "new",
        delta: null,
        from: was,
        text: !was ? "new" : was > h.rank ? `new, ↑${was - h.rank} (was #${was})` : `new (was #${was})`,
      });
    } else if (before > h.rank) {
      const delta = before - h.rank;
      out.set(h.chunk.id, { kind: "up", delta, from: before, text: `↑${delta} (was #${before})` });
    } else if (before < h.rank) {
      const delta = h.rank - before;
      out.set(h.chunk.id, { kind: "down", delta, from: before, text: `↓${delta} (was #${before})` });
    } else {
      out.set(h.chunk.id, { kind: "same", delta: 0, from: before, text: "no change" });
    }
  }
  return out;
}

/** Fused hits that the reranker pushed out of the shown top-k (so the reader sees what was dropped). */
export function droppedByRerank(fusedHits: SearchHit[], rerankedHits: SearchHit[]): SearchHit[] {
  const kept = new Set(rerankedHits.map((h) => h.chunk.id));
  return fusedHits.filter((h) => !kept.has(h.chunk.id));
}

export const BADGE_COLORS = [
  "bg-sky-100 text-sky-900 ring-sky-400",
  "bg-amber-100 text-amber-900 ring-amber-400",
  "bg-emerald-100 text-emerald-900 ring-emerald-400",
  "bg-rose-100 text-rose-900 ring-rose-400",
  "bg-violet-100 text-violet-900 ring-violet-400",
  "bg-orange-100 text-orange-900 ring-orange-400",
  "bg-teal-100 text-teal-900 ring-teal-400",
  "bg-fuchsia-100 text-fuchsia-900 ring-fuchsia-400",
];

export type ChunkBadge = { letter: string; color: string; columns: ColumnKey[] };

const letterFor = (i: number) => {
  let s = "";
  let n = i;
  do {
    s = String.fromCharCode(65 + (n % 26)) + s;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return s;
};

/**
 * Give every chunk that shows up in two or more columns a letter and a colour (letter first, colour second, so
 * colour never carries the meaning alone). Chunks seen in only one column get no badge. Letters are assigned in
 * the order chunks are met when reading the columns left to right, top to bottom.
 */
export function assignBadges(lists: Partial<Record<ColumnKey, SearchHit[]>>): Map<string, ChunkBadge> {
  const order: ColumnKey[] = ["bm25", "vector", "fused", "reranked"];
  const seenIn = new Map<string, ColumnKey[]>();
  for (const key of order) {
    for (const h of lists[key] ?? []) {
      const cols = seenIn.get(h.chunk.id) ?? [];
      if (!cols.includes(key)) cols.push(key);
      seenIn.set(h.chunk.id, cols);
    }
  }
  const badges = new Map<string, ChunkBadge>();
  let n = 0;
  for (const [id, columns] of seenIn) {
    if (columns.length < 2) continue;
    badges.set(id, { letter: letterFor(n), color: BADGE_COLORS[n % BADGE_COLORS.length]!, columns });
    n++;
  }
  return badges;
}

export type RankInfo = { rank: number; shown: boolean };

/**
 * Each chunk's rank in every column it appears in (for the "rank in other columns" line). Hits from the fused and
 * reranked searches also carry the rank each method gave the chunk even when it falls outside the top k; those fill
 * the gaps with `shown: false`.
 */
export function ranksAcrossColumns(
  lists: Partial<Record<ColumnKey, SearchHit[]>>,
): Map<string, Partial<Record<ColumnKey, RankInfo>>> {
  const out = new Map<string, Partial<Record<ColumnKey, RankInfo>>>();
  const slot = (id: string) => {
    const r = out.get(id) ?? {};
    out.set(id, r);
    return r;
  };
  for (const col of COLUMNS) {
    for (const h of lists[col.key] ?? []) slot(h.chunk.id)[col.key] = { rank: h.rank, shown: true };
  }
  for (const h of [...(lists.reranked ?? []), ...(lists.fused ?? [])]) {
    const r = slot(h.chunk.id);
    const known: [ColumnKey, number | null][] = [
      ["bm25", h.scores.bm25_rank],
      ["vector", h.scores.vector_rank],
      ["fused", h.scores.rrf_rank],
      ["reranked", h.scores.rerank_rank],
    ];
    for (const [key, rank] of known) if (rank !== null && !r[key]) r[key] = { rank, shown: false };
  }
  return out;
}

/** `001-57619§88` → the case-viewer link `/case/001-57619#p88`. */
export function paragraphLink(paragraphId: string): { href: string; ref: string } {
  const i = paragraphId.indexOf("§");
  const docId = paragraphId.slice(0, i);
  const ref = paragraphId.slice(i + 1);
  return { href: `/case/${encodeURIComponent(docId)}#p${ref}`, ref };
}

/** First `max` characters, cut at a word boundary, with an ellipsis when shortened. */
export function snippet(text: string, max = 260): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max);
  const lastSpace = cut.lastIndexOf(" ");
  return `${(lastSpace > max * 0.6 ? cut.slice(0, lastSpace) : cut).replace(/[\s,;:.]+$/, "")}…`;
}

/** The timing line for a column: the method's own stage(s) plus total, from `SearchResult.timings_ms`. */
export function timingText(key: ColumnKey, result: SearchResult): string {
  const t = result.timings_ms;
  const ms = (v: number | null) => (v === null ? null : `${Math.round(v)} ms`);
  const parts: (string | null)[] =
    key === "bm25"
      ? [ms(t.bm25) && `keyword search ${ms(t.bm25)}`]
      : key === "vector"
        ? [ms(t.vector) && `embed + nearest-neighbour ${ms(t.vector)}`]
        : key === "fused"
          ? [
              ms(t.bm25) && `BM25 ${ms(t.bm25)}`,
              ms(t.vector) && `vector ${ms(t.vector)}`,
              ms(t.fuse) && `fuse ${ms(t.fuse)}`,
            ]
          : [
              ms(t.bm25) && `BM25 ${ms(t.bm25)}`,
              ms(t.vector) && `vector ${ms(t.vector)}`,
              ms(t.fuse) && `fuse ${ms(t.fuse)}`,
              ms(t.rerank) && `rerank ${ms(t.rerank)}`,
            ];
  const stages = parts.filter(Boolean).join(" · ");
  return `${stages ? `${stages} · ` : ""}total ${Math.round(t.total)} ms`;
}
