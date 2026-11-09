import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import fixture from "@echr/contract/fixtures/SearchResult.json";
import type { SearchResult } from "@echr/contract";
import type { ApiResult } from "@/lib/api";
import { LabColumn } from "./_components/lab-column";
import { COLUMNS, assignBadges, ranksAcrossColumns, type SearchHit } from "./lab-model";

const data = fixture as SearchResult;
const hits = data.hits as SearchHit[];
const col = (key: string) => COLUMNS.find((c) => c.key === key)!;
const ctx = (lists = {}) => ({ badges: assignBadges(lists), ranks: ranksAcrossColumns(lists), movements: new Map() });

describe("LabColumn", () => {
  it("renders hits with score label, links and the explanation", () => {
    const html = renderToString(<LabColumn col={col("fused")} result={{ ok: true, data, ms: 55 }} ctx={ctx()} />);
    expect(html).toContain('data-testid="lab-column-fused"');
    expect(html).toContain("RRF score");
    expect(html).toContain('href="/case/001-57619#p81"');
    expect(html).toContain("What you’re seeing");
    expect(html.match(/data-testid="lab-hit"/g)).toHaveLength(hits.length);
  });

  it("says so when reranking is switched off instead of failing", () => {
    const html = renderToString(<LabColumn col={col("reranked")} result={{ ok: true, data, ms: 55 }} ctx={ctx()} />);
    expect(html).toContain("Reranking is switched off");
  });

  it("renders an API error readably", () => {
    const result: ApiResult<SearchResult> = {
      ok: false,
      error: "fetch failed",
      status: null,
      apiError: null,
      ms: 3,
    };
    const html = renderToString(<LabColumn col={col("bm25")} result={result} ctx={ctx()} />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("This search failed.");
    expect(html).toContain("fetch failed");
    expect(html).toContain("Could not reach the API");
  });

  it("shows a message for an empty result", () => {
    const html = renderToString(
      <LabColumn col={col("vector")} result={{ ok: true, data: { ...data, hits: [] }, ms: 5 }} ctx={ctx()} />,
    );
    expect(html).toContain("No passages matched.");
  });
});
