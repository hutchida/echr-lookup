import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  DOC_TYPE_LABELS,
  MCP_LIMITS,
  MCP_TOOLS,
  McpCheckQuoteResult,
  McpGetParagraphsResult,
  McpSearchCaseLawInput,
  McpSearchCaseLawResult,
  mcpRegistry,
} from "../src/mcp";
import { listFixtures, readJson, root } from "./helpers";

const bytes = (v: unknown) => Buffer.byteLength(JSON.stringify(v), "utf8");
const fixture = (file: string) => readJson(join(root, "fixtures", file));
const resultFixtures = listFixtures().filter((f) => f.name.startsWith("Mcp") && f.name.endsWith("Result"));

describe("MCP tools", () => {
  it("six tools, each with an input and a result schema in the registry", () => {
    expect(Object.keys(MCP_TOOLS).sort()).toEqual(
      ["check_quote", "corpus_info", "count_cases", "get_case", "get_paragraphs", "search_case_law"].sort(),
    );
    for (const [input, result] of Object.values(MCP_TOOLS)) {
      expect(Object.values(mcpRegistry)).toContain(input);
      expect(Object.values(mcpRegistry)).toContain(result);
    }
  });

  it.each(resultFixtures.map((f) => f.file))("%s: at most 25 KB as compact JSON and carries the corpus block", (file) => {
    const value = fixture(file) as { corpus?: { documents: number } };
    expect(bytes(value)).toBeLessThanOrEqual(MCP_LIMITS.resultMaxBytes);
    expect(value.corpus?.documents).toBeGreaterThan(0);
  });

  it.each(Object.keys(mcpRegistry))("schema/%s.json is MCP-ready: one $ref to a self-contained object schema", (name) => {
    const text = readFileSync(join(root, "schema", `${name}.json`), "utf8");
    const json = JSON.parse(text) as { $ref: string; $defs: Record<string, { type: string }> };
    expect(json.$ref).toBe(`#/$defs/${name}`);
    expect(Object.keys(json.$defs)).toEqual([name]);
    expect(json.$defs[name]!.type).toBe("object");
    expect(text.split("$ref").length - 1, "no nested $ref: MCP clients need the schema inline").toBe(1);
  });
});

describe("search_case_law", () => {
  const result = fixture("McpSearchCaseLawResult.json") as McpSearchCaseLawResult;

  it("limit and hits are capped at 10", () => {
    expect(McpSearchCaseLawInput.safeParse({ query: "x", limit: 10 }).success).toBe(true);
    expect(McpSearchCaseLawInput.safeParse({ query: "x", limit: 11 }).success).toBe(false);
    const hit = result.hits[0]!;
    const many = (n: number) => ({ ...result, hits: Array.from({ length: n }, (_, i) => ({ ...hit, rank: i + 1 })) });
    expect(McpSearchCaseLawResult.safeParse(many(10)).success).toBe(true);
    expect(McpSearchCaseLawResult.safeParse(many(11)).success).toBe(false);
  });

  it("worst case (10 hits, every field at its limit) stays under 25 KB", () => {
    const hit = result.hits[0]!;
    const worstHit = {
      ...hit,
      paragraph_id: `${"0".repeat(40)}§${"9".repeat(23)}`,
      doc_id: "0".repeat(40),
      case_name: "N".repeat(MCP_LIMITS.caseNameMaxChars),
      articles: Array.from({ length: MCP_LIMITS.articlesMax }, () => "P12-1-a-b"),
      quote: "q".repeat(MCP_LIMITS.quoteMaxChars),
      para_label: "p".repeat(MCP_LIMITS.paraLabelMaxChars),
      hudoc_url: `https://hudoc.echr.coe.int/eng?i=${"0".repeat(60)}#:~:text=${"%2D".repeat(40)}`,
      cite: "c".repeat(MCP_LIMITS.citeMaxChars),
    };
    const worst = {
      query: "q".repeat(500),
      filters: "f".repeat(300),
      hits: Array.from({ length: MCP_LIMITS.searchMaxHits }, (_, i) => ({ ...worstHit, rank: i + 1 })),
      corpus: { ...result.corpus, scope: "s".repeat(200), sample_note: "n".repeat(300) },
    };
    expect(McpSearchCaseLawResult.safeParse(worst).error?.issues ?? []).toEqual([]);
    const size = bytes(worst);
    console.log(`worst-case search_case_law result: ${size} bytes`);
    expect(size).toBeLessThanOrEqual(MCP_LIMITS.resultMaxBytes);
  });

  it("each hit: one paragraph, no duplicates, label matches type, cite ends with the para_label", () => {
    const ids = result.hits.map((h) => h.paragraph_id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const h of result.hits) {
      expect(h.paragraph_id.startsWith(`${h.doc_id}§`)).toBe(true);
      expect(h.doc_type_label).toBe(DOC_TYPE_LABELS[h.doc_type]);
      expect(h.cite).toBe(`[${h.case_name}, ${h.doc_type_label}, ${h.para_label}]`);
    }
  });

  it("para_label: '§<number>' for a numbered paragraph, '<Section>, para <n>' for an unnumbered one", () => {
    for (const h of result.hits) {
      const ref = h.paragraph_id.split("§")[1]!;
      if (/^\d+$/.test(ref)) expect(h.para_label).toBe(`§${ref}`);
      else expect(h.para_label).toMatch(/^[A-Za-z ]+, para \d+$/);
    }
  });

  it("hudoc_url ends in a text fragment made of the quote's first words", () => {
    for (const h of result.hits) {
      expect(h.hudoc_url).toMatch(/^https:\/\/[^#]+#:~:text=[^#&,-]+$/);
      const words = decodeURIComponent(h.hudoc_url.split(":~:text=")[1]!).split(" ");
      expect(words.length).toBeGreaterThanOrEqual(6);
      expect(words.length).toBeLessThanOrEqual(8);
      expect(h.quote.replace(/^…/, "").startsWith(words.join(" "))).toBe(true);
    }
  });
});

describe("cross-fixture consistency (real snapshot data)", () => {
  it("check_quote's quote is verbatim in get_paragraphs' text for the same paragraph", () => {
    const quote = fixture("McpCheckQuoteResult.json") as McpCheckQuoteResult;
    const paras = fixture("McpGetParagraphsResult.json") as McpGetParagraphsResult;
    const p = paras.paragraphs.find((x) => x.paragraph_id === quote.paragraph_id);
    expect(p?.requested).toBe(true);
    expect(p!.text).toContain(quote.closest_match!);
  });

  it("count_cases: the answer cites no paragraph (the SQL is the evidence) and states every number", () => {
    for (const file of ["McpCountCasesResult.json", "McpCountCasesResult.top-group.json"]) {
      const r = fixture(file) as { answer: string; count: number; scope_total: number | null };
      expect(r.answer).not.toMatch(/§/);
      expect(r.answer).toContain(String(r.count));
      if (r.scope_total !== null) expect(r.answer).toContain(String(r.scope_total));
    }
  });
});
