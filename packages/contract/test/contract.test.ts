import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { z } from "zod";
import { CaseDetail } from "../src/case-detail";
import { CorpusStats } from "../src/corpus-stats";
import { EvalRunList, IngestRunList } from "../src/lists";
import { ManifestEntry } from "../src/source-document";
import { SearchResult } from "../src/search";
import { Citation, MatchingCase, StatsQueryResult } from "../src/stats";
import { toJsonSchemas } from "../src/json-schema";
import { registry } from "../src/registry";
import { dataPaths, listFixtures, readJson, repoRoot, root, schemaPaths } from "./helpers";

const names = Object.keys(registry);
const fixtures = listFixtures();

describe("fixtures", () => {
  it.each(fixtures.map((f) => f.file))("%s validates against its zod schema (strict: unknown fields fail)", (file) => {
    const f = fixtures.find((x) => x.file === file)!;
    const schema = registry[f.name];
    expect(schema, `no schema named ${f.name}`).toBeDefined();
    const result = schema!.safeParse(readJson(join(root, "fixtures", file)));
    expect(result.error?.issues ?? []).toEqual([]);
  });

  it("naming rule: every fixture is <Name>.json or <Name>.<variant>.json, and every schema has a primary <Name>.json", () => {
    for (const f of fixtures) expect(names, `${f.file}: unknown schema ${f.name}`).toContain(f.name);
    const primary = fixtures.filter((f) => f.variant === null).map((f) => f.name);
    expect(primary.sort()).toEqual([...names].sort());
  });

  it.each(names)("%s: every schema property (optional ones included) appears in at least one fixture", (name) => {
    const covered = new Set(
      fixtures.filter((f) => f.name === name).flatMap((f) => dataPaths(readJson(join(root, "fixtures", f.file)))),
    );
    const missing = [...new Set(schemaPaths(registry[name]!))].filter((p) => !covered.has(p));
    expect(missing, `${name}: schema fields with no fixture example (add a fixture or ${name}.<variant>.json)`).toEqual([]);
  });

  it("no field exists only in a fixture: every fixture path is in the schema", () => {
    for (const f of fixtures) {
      const known = new Set(schemaPaths(registry[f.name]!));
      const extra = [...new Set(dataPaths(readJson(join(root, "fixtures", f.file))))].filter((p) => !known.has(p));
      expect(extra, `${f.file}: fields not in the schema`).toEqual([]);
    }
  });
});

const fixture = (name: string): unknown => readJson(join(root, "fixtures", `${name}.json`));

/** Ground fields must be null together, or both set. */
function groundsConsistent(doc: { inadmissibility_grounds: unknown[] | null; inadmissibility_grounds_source: string | null }) {
  return (doc.inadmissibility_grounds === null) === (doc.inadmissibility_grounds_source === null);
}

describe("response shapes", () => {
  it("answer-first fixture: one short_answer, it is the first claim, and points carry a group; old fixtures have neither field", () => {
    const first = registry.Answer!.parse(fixture("Answer.answer-first")) as { claims: { role?: string; group?: string }[] };
    expect(first.claims.filter((c) => c.role === "short_answer").length).toBe(1);
    expect(first.claims[0]?.role).toBe("short_answer");
    expect(first.claims.slice(1).every((c) => c.role === "point" && typeof c.group === "string")).toBe(true);
    const old = registry.Answer!.parse(fixture("Answer")) as { claims: { role?: string; group?: string }[] };
    expect(old.claims.every((c) => c.role === undefined && c.group === undefined)).toBe(true);
  });

  it("inadmissibility grounds and their source are null together (SourceDocument, CaseDetail, ManifestEntry fixtures)", () => {
    const sd = registry.SourceDocument!.parse(fixture("SourceDocument")) as Parameters<typeof groundsConsistent>[0];
    expect(groundsConsistent(sd)).toBe(true);
    expect(sd.inadmissibility_grounds_source, "SourceDocument fixture should show text-extracted grounds").toBe("text");
    expect(sd.inadmissibility_grounds?.length ?? 0).toBeGreaterThan(0);
    expect(groundsConsistent(CaseDetail.parse(fixture("CaseDetail")).document)).toBe(true);
    expect(groundsConsistent(ManifestEntry.parse(fixture("ManifestEntry")))).toBe(true);
  });

  it("CaseDetail: paragraphs belong to the document, ids are unique and `<doc>§<ref>`", () => {
    const c = CaseDetail.parse(fixture("CaseDetail"));
    expect(c.paragraphs.length).toBeGreaterThan(0);
    for (const p of c.paragraphs) {
      expect(p.doc_id).toBe(c.document.item_id);
      expect(p.id.startsWith(`${c.document.item_id}§`)).toBe(true);
    }
    expect(new Set(c.paragraphs.map((p) => p.id)).size).toBe(c.paragraphs.length);
  });

  it("CorpusStats: breakdowns add up to totals.documents; by_article is sorted most frequent first", () => {
    const s = CorpusStats.parse(fixture("CorpusStats"));
    const sum = (b: { count: number }[]) => b.reduce((a, x) => a + x.count, 0);
    for (const b of [s.by_doc_type, s.by_outcome, s.by_chamber, s.by_year]) expect(sum(b)).toBe(s.totals.documents);
    const counts = s.by_article.map((x) => x.count);
    expect(counts).toEqual([...counts].sort((a, b) => b - a));
    const years = s.by_year.map((x) => x.key!);
    expect(years).toEqual([...years].sort());
    expect(s.costs.total_usd).toBeCloseTo(s.costs.by_purpose.reduce((a, x) => a + x.cost_usd, 0), 6);
  });

  it("CostSummary: by_purpose and by_model add up to the totals; recent is newest first", () => {
    const c = registry.CostSummary!.parse(fixture("CostSummary")) as {
      total_usd: number;
      by_purpose: { calls: number; cost_usd: number }[];
      by_model: { calls: number; cost_usd: number }[];
      recent: { timestamp: string }[];
    };
    const calls = (b: { calls: number }[]) => b.reduce((a, x) => a + x.calls, 0);
    expect(calls(c.by_purpose)).toBe(calls(c.by_model));
    expect(c.by_model.reduce((a, x) => a + x.cost_usd, 0)).toBeCloseTo(c.total_usd, 6);
    const t = c.recent.map((e) => e.timestamp);
    expect(t).toEqual([...t].sort().reverse());
  });

  it("run lists are newest first and the summary matches the full EvalRun", () => {
    const ingest = IngestRunList.parse(fixture("IngestRunList")).runs.map((r) => r.started_at);
    expect(ingest).toEqual([...ingest].sort().reverse());
    const evals = EvalRunList.parse(fixture("EvalRunList")).runs;
    expect(evals.map((r) => r.started_at)).toEqual(evals.map((r) => r.started_at).sort().reverse());
    const full = registry.EvalRun!.parse(fixture("EvalRun")) as { run_id: string; items: unknown[] };
    const summary = evals.find((r) => r.run_id === full.run_id)!;
    expect(summary.item_count).toBe(full.items.length);
  });

  it("run lists above 50 entries fail", () => {
    const ir = IngestRunList.parse(fixture("IngestRunList")).runs[0]!;
    expect(IngestRunList.safeParse({ runs: Array.from({ length: 50 }, () => ir) }).success).toBe(true);
    expect(IngestRunList.safeParse({ runs: Array.from({ length: 51 }, () => ir) }).success).toBe(false);
  });
});

describe("citations and matching cases", () => {
  const answer = readJson(join(root, "fixtures", "Answer.json")) as { citations: Record<string, unknown>[] };
  const stats = readJson(join(root, "fixtures", "StatsQueryResult.json")) as Record<string, unknown> & {
    matching_cases: Record<string, unknown>[];
  };

  it("a citation must say which kind of document it cites (a legal summary is not the judgment)", () => {
    const withoutType = { ...answer.citations[0] };
    delete withoutType.doc_type;
    expect(Citation.safeParse(withoutType).success).toBe(false);
    expect(Citation.safeParse({ ...answer.citations[0], doc_type: "legal_summary" }).success).toBe(true);
    expect(Citation.safeParse({ ...answer.citations[0], doc_type: "summary" }).success).toBe(false);
  });

  it("a matching case may list the case with no quoted paragraph", () => {
    const bare = { ...stats.matching_cases[0], paragraph_id: null, quote: "", link_target: "/case/001-231646" };
    expect(MatchingCase.safeParse(bare).error?.issues ?? []).toEqual([]);
    expect(Citation.safeParse(bare).success).toBe(false); // an inline citation always names its paragraph
  });

  it("scope_total is required: null, or the documents before the outcome filter", () => {
    const without: Record<string, unknown> = { ...stats };
    delete without.scope_total;
    expect(StatsQueryResult.safeParse(without).success).toBe(false);
    expect(StatsQueryResult.safeParse({ ...stats, scope_total: 10, count: 9 }).success).toBe(true);
  });
});

describe("limits", () => {
  it("SearchResult with 51 hits fails; 50 passes", () => {
    const fx = SearchResult.parse(readJson(join(root, "fixtures", "SearchResult.json")));
    const withHits = (n: number) => ({ ...fx, hits: Array.from({ length: n }, (_, i) => ({ ...fx.hits[0]!, rank: i + 1 })) });
    expect(SearchResult.safeParse(withHits(50)).success).toBe(true);
    expect(SearchResult.safeParse(withHits(51)).success).toBe(false);
  });

  it("SearchRequest k above 50 fails", () => {
    const fx = readJson(join(root, "fixtures", "SearchRequest.json")) as Record<string, unknown>;
    expect(registry.SearchRequest!.safeParse({ ...fx, k: 51 }).success).toBe(false);
    expect(registry.SearchRequest!.safeParse({ ...fx, k: 0 }).success).toBe(false);
  });

  it("a search hit's paragraph_ids stay within its chunk's paragraph_ids (documented rule, checked on the fixture)", () => {
    const fx = SearchResult.parse(readJson(join(root, "fixtures", "SearchResult.json")));
    for (const h of fx.hits) for (const p of h.paragraph_ids) expect(h.chunk.paragraph_ids).toContain(p);
  });
});

describe("generated schema files", () => {
  it("schema/*.json is up to date (run `pnpm contract:export` if this fails)", () => {
    for (const [name, json] of Object.entries(toJsonSchemas())) {
      expect(readFileSync(join(root, "schema", `${name}.json`), "utf8"), name).toBe(json);
    }
  });
});

describe("snapshot manifest", () => {
  it("data/snapshot/manifest.json is a list of valid ManifestEntry with unique item ids and paths", () => {
    const manifest = readJson(join(repoRoot, "data", "snapshot", "manifest.json"));
    const parsed = z.array(ManifestEntry).min(1).safeParse(manifest);
    expect(parsed.error?.issues ?? []).toEqual([]);
    const entries = parsed.data!;
    for (const e of entries) expect(groundsConsistent(e), e.item_id).toBe(true);
    for (const e of entries) if (e.inadmissibility_grounds_source) expect(e.inadmissibility_grounds_source).toBe("metadata");
    expect(new Set(entries.map((e) => e.item_id)).size).toBe(entries.length);
    expect(new Set(entries.map((e) => e.path)).size).toBe(entries.length);
  });
});
