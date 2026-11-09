import { describe, expect, it } from "vitest";
import fixture from "@echr/contract/fixtures/SearchResult.json";
import type { SearchResult } from "@echr/contract";
import {
  COLUMNS,
  DEFAULT_K,
  DEMO_QUERY,
  assignBadges,
  buildRequest,
  droppedByRerank,
  labHref,
  paragraphLink,
  parseLabParams,
  rankMovements,
  ranksAcrossColumns,
  rerankDisabled,
  scoreOf,
  snippet,
  timingText,
  type SearchHit,
} from "./lab-model";

const result = fixture as SearchResult;
const hits = result.hits as SearchHit[];

const withRank = (h: SearchHit, rank: number, extra: Partial<SearchHit["scores"]> = {}): SearchHit => ({
  ...h,
  rank,
  scores: { ...h.scores, ...extra },
});

describe("parseLabParams", () => {
  it("uses the demo query and defaults when nothing is given", () => {
    expect(parseLabParams({})).toEqual({
      q: DEMO_QUERY,
      chunking: "recursive",
      k: DEFAULT_K,
      article: null,
      docType: null,
    });
  });

  it("reads valid values, taking the first of repeated params", () => {
    const p = parseLabParams({ q: ["  death row  ", "x"], chunking: "by_section", k: "5", article: "8", doc_type: "judgment" });
    expect(p).toEqual({ q: "death row", chunking: "by_section", k: 5, article: "8", docType: "judgment" });
  });

  it("falls back on invalid values and clamps k", () => {
    expect(parseLabParams({ q: "   ", chunking: "nope", k: "abc", article: "8; DROP", doc_type: "novel" })).toEqual({
      q: DEMO_QUERY,
      chunking: "recursive",
      k: DEFAULT_K,
      article: null,
      docType: null,
    });
    expect(parseLabParams({ k: "0" }).k).toBe(1);
    expect(parseLabParams({ k: "999" }).k).toBe(50);
    expect(parseLabParams({ k: "-3" }).k).toBe(DEFAULT_K);
    expect(parseLabParams({ k: "2.5" }).k).toBe(DEFAULT_K);
  });

  it("truncates an over-long query to the contract limit", () => {
    expect(parseLabParams({ q: "a".repeat(900) }).q).toHaveLength(500);
  });
});

describe("buildRequest / labHref", () => {
  it("builds one request per mode, with filters only when set", () => {
    const params = parseLabParams({ q: "x", article: "3", doc_type: "judgment" });
    expect(buildRequest(params, "vector")).toEqual({
      query: "x",
      mode: "vector",
      chunking: "recursive",
      k: 10,
      filters: { article: "3", doc_types: ["judgment"] },
    });
    expect(buildRequest(parseLabParams({ q: "x" }), "bm25")).not.toHaveProperty("filters");
  });

  it("round-trips through the URL", () => {
    const p = parseLabParams({ q: "death row? & more", chunking: "fixed", k: "7", article: "P1-3" });
    const url = new URL(labHref(p), "http://x");
    const back = parseLabParams(Object.fromEntries(url.searchParams));
    expect(back).toEqual(p);
  });
});

describe("scoreOf", () => {
  const hit = hits[0]!;
  it("labels each column's own score", () => {
    expect(scoreOf("bm25", hit)).toMatchObject({ label: "BM25 score", text: "22.52" });
    expect(scoreOf("vector", hit)).toMatchObject({ label: "cosine similarity", text: "0.792" });
    expect(scoreOf("fused", hit)).toMatchObject({ label: "RRF score", text: "0.0323" });
  });
  it("shows the cross-encoder score to four places (it saturates near 1)", () => {
    const hit = withRank(hits[0]!, 1, { rerank_score: 0.9999308586120605, rerank_rank: 1 });
    expect(scoreOf("reranked", hit).text).toBe("0.9999");
  });
  it("shows n/a for a method that did not run", () => {
    expect(scoreOf("reranked", hit)).toMatchObject({ label: "cross-encoder score", value: null, text: "n/a" });
  });
  it("has a column for each search mode", () => {
    expect(COLUMNS.map((c) => c.mode)).toEqual(["bm25", "vector", "hybrid", "hybrid_rerank"]);
  });
});

describe("rerankDisabled", () => {
  it("is true when no hit carries a rerank score, false otherwise", () => {
    expect(rerankDisabled(result)).toBe(true);
    const scored = { ...result, hits: hits.map((h) => withRank(h, h.rank, { rerank_score: 0.9, rerank_rank: h.rank })) };
    expect(rerankDisabled(scored)).toBe(false);
    expect(rerankDisabled({ ...result, hits: [] })).toBe(false);
  });
});

describe("rankMovements", () => {
  const fused = hits.slice(0, 3);
  it("marks up, down, same and new", () => {
    const reranked = [
      withRank(fused[2]!, 1), // was 3 -> up 2
      withRank(fused[0]!, 2), // was 1 -> down 1
      withRank(fused[1]!, 3), // was 2 -> down 1
      withRank(hits[3]!, 4, { rrf_rank: 4 }), // not in the fused top 3 -> new
    ];
    const m = rankMovements(fused, reranked);
    expect(m.get(fused[2]!.chunk.id)).toMatchObject({ kind: "up", delta: 2, from: 3, text: "↑2 (was #3)" });
    expect(m.get(fused[0]!.chunk.id)).toMatchObject({ kind: "down", delta: 1, text: "↓1 (was #1)" });
    expect(m.get(hits[3]!.chunk.id)).toMatchObject({ kind: "new", from: 4, text: "new (was #4)" });
    const risen = rankMovements(fused, [withRank(hits[3]!, 1, { rrf_rank: 14 })]);
    expect(risen.get(hits[3]!.chunk.id)?.text).toBe("new, ↑13 (was #14)");
  });

  it("reports unchanged and brand-new chunks", () => {
    const same = rankMovements(fused, fused);
    expect([...same.values()].every((v) => v.kind === "same")).toBe(true);
    const fresh = { ...fused[0]!, rank: 1, chunk: { ...fused[0]!.chunk, id: "zzz:recursive:9" }, scores: { ...fused[0]!.scores, rrf_rank: 17 } };
    expect(rankMovements(fused, [fresh]).get("zzz:recursive:9")).toEqual({
      kind: "new",
      delta: null,
      from: 17,
      text: "new, ↑16 (was #17)",
    });
    expect(rankMovements([], [withRank(fused[0]!, 1, { rrf_rank: null })]).get(fused[0]!.chunk.id)?.text).toBe("new");
  });
});

describe("droppedByRerank", () => {
  it("lists fused hits that are missing from the reranked list", () => {
    const fused = hits.slice(0, 3);
    expect(droppedByRerank(fused, [fused[1]!]).map((h) => h.rank)).toEqual([1, 3]);
  });
});

describe("assignBadges", () => {
  const [a, b, c] = hits;
  it("badges only chunks that appear in two or more columns, with distinct letters", () => {
    const badges = assignBadges({
      bm25: [a!, b!],
      vector: [withRank(b!, 1), withRank(c!, 2)],
      fused: [a!],
    });
    expect([...badges.keys()].sort()).toEqual([a!.chunk.id, b!.chunk.id].sort());
    expect(badges.get(a!.chunk.id)).toMatchObject({ letter: "A", columns: ["bm25", "fused"] });
    expect(badges.get(b!.chunk.id)).toMatchObject({ letter: "B", columns: ["bm25", "vector"] });
    expect(badges.has(c!.chunk.id)).toBe(false);
  });

  it("keeps assigning unique letters beyond Z and cycles colours", () => {
    const many: SearchHit[] = Array.from({ length: 30 }, (_, i) => ({
      ...a!,
      rank: i + 1,
      chunk: { ...a!.chunk, id: `d:recursive:${i}` },
    }));
    const badges = assignBadges({ bm25: many, vector: many });
    const letters = [...badges.values()].map((x) => x.letter);
    expect(new Set(letters).size).toBe(30);
    expect(letters[26]).toBe("AA");
  });
});

describe("ranksAcrossColumns", () => {
  it("collects a chunk's rank per column", () => {
    const m = ranksAcrossColumns({ bm25: [withRank(hits[0]!, 4)], fused: [hits[0]!] });
    expect(m.get(hits[0]!.chunk.id)).toMatchObject({ bm25: { rank: 4, shown: true }, fused: { rank: 1, shown: true } });
  });

  it("fills gaps from the ranks carried on fused/reranked hits, marked as not shown", () => {
    const h = withRank(hits[0]!, 1, { bm25_rank: 40, vector_rank: null, rrf_rank: 26, rerank_rank: 1 });
    const m = ranksAcrossColumns({ reranked: [h] }).get(h.chunk.id)!;
    expect(m.reranked).toEqual({ rank: 1, shown: true });
    expect(m.bm25).toEqual({ rank: 40, shown: false });
    expect(m.fused).toEqual({ rank: 26, shown: false });
    expect(m.vector).toBeUndefined();
  });
});

describe("paragraphLink / snippet / timingText", () => {
  it("links a paragraph id to the case viewer anchor", () => {
    expect(paragraphLink("001-57619§88")).toEqual({ href: "/case/001-57619#p88", ref: "88" });
    expect(paragraphLink("001-57619§op1").href).toBe("/case/001-57619#pop1");
  });

  it("cuts long text at a word boundary and leaves short text alone", () => {
    expect(snippet("short   text\nhere")).toBe("short text here");
    const long = "word ".repeat(200);
    const s = snippet(long, 50);
    expect(s.endsWith("…")).toBe(true);
    expect(s.length).toBeLessThanOrEqual(51);
    expect(s).not.toMatch(/wor…$/);
  });

  it("describes the stages each column ran", () => {
    const r = { ...result, timings_ms: { bm25: 37.4, vector: 18.2, fuse: 0.3, rerank: 900.8, total: 960.1 } };
    expect(timingText("bm25", r)).toBe("keyword search 37 ms · total 960 ms");
    expect(timingText("reranked", r)).toContain("rerank 901 ms");
    expect(timingText("fused", r)).toContain("fuse 0 ms");
    expect(timingText("vector", { ...r, timings_ms: { ...r.timings_ms, vector: null } })).toBe("total 960 ms");
  });
});
