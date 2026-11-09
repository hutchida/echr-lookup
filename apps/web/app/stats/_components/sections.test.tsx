import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import corpusStats from "@echr/contract/fixtures/CorpusStats.json";
import costSummary from "@echr/contract/fixtures/CostSummary.json";
import evalRunList from "@echr/contract/fixtures/EvalRunList.json";
import ingestRunList from "@echr/contract/fixtures/IngestRunList.json";
import { CorpusStats, CostSummary, EvalRunList, IngestRunList } from "@echr/contract";
import type { ApiResult } from "@/lib/api";
import { CorpusSection } from "./CorpusSection";
import { CostSection } from "./CostSection";
import { EvalSection } from "./EvalSection";
import { IngestSection } from "./IngestSection";

const ok = <T,>(data: T): ApiResult<T> => ({ ok: true, data, ms: 5 });
const fail = (status: number | null = 500): ApiResult<never> => ({ ok: false, error: "boom", status, apiError: null, ms: 5 });

describe("section rendering", () => {
  it("renders every section from the contract fixtures", () => {
    const html = [
      renderToString(<CorpusSection result={ok(CorpusStats.parse(corpusStats))} />),
      renderToString(<IngestSection result={ok(IngestRunList.parse(ingestRunList))} />),
      renderToString(<CostSection result={ok(CostSummary.parse(costSummary))} />),
      renderToString(<EvalSection result={ok(EvalRunList.parse(evalRunList))} />),
    ];
    expect(html[0]).toContain('data-testid="stats-counts"');
    expect(html[0]).toContain("snapshot");
    expect(html[0]).toContain("7,422");
    expect(html[1]).toContain('data-testid="stats-ingest"');
    expect(html[1]).toContain("1 min 43 s");
    expect(html[2]).toContain('data-testid="stats-costs"');
    expect(html[2]).toContain("$0.00");
    expect(html[3]).toContain('data-testid="stats-eval"');
    expect(html[3]).toContain("0.07");
  });

  it("renders an independent, readable error in each section", () => {
    for (const [html, testId] of [
      [renderToString(<CorpusSection result={fail()} />), "stats-counts"],
      [renderToString(<IngestSection result={fail(null)} />), "stats-ingest"],
      [renderToString(<CostSection result={fail(404)} />), "stats-costs"],
      [renderToString(<EvalSection result={fail()} />), "stats-eval"],
    ] as const) {
      expect(html).toContain(`data-testid="${testId}"`);
      expect(html).toContain("Could not load");
      expect(html).toContain("boom");
    }
  });

  it("renders empty states", () => {
    expect(renderToString(<IngestSection result={ok({ runs: [] })} />)).toContain("No ingestion run recorded yet");
    expect(renderToString(<EvalSection result={ok({ runs: [] })} />)).toContain("No evaluation runs yet");
  });
});
