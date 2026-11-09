import { describe, expect, it } from "vitest";
import corpusStats from "@echr/contract/fixtures/CorpusStats.json";
import costSummary from "@echr/contract/fixtures/CostSummary.json";
import evalRun from "@echr/contract/fixtures/EvalRun.json";
import evalRunList from "@echr/contract/fixtures/EvalRunList.json";
import ingestRunList from "@echr/contract/fixtures/IngestRunList.json";
import { CorpusStats, type EvalRunSummary, CostSummary, EvalRun, EvalRunList, IngestRunList } from "@echr/contract";
import {
  articleLabel,
  barPercent,
  bestPerMetric,
  bucketRows,
  buildEvalTable,
  costRequestCount,
  formatMetric,
  formatMs,
  formatSeconds,
  formatTimestamp,
  formatTokens,
  formatUsd,
  humanise,
  isAnswerLevel,
  type MetricKey,
  sharePercent,
  stageRows,
  totalStageSeconds,
  wallSeconds,
} from "./format";

const stats = CorpusStats.parse(corpusStats);
const costs = CostSummary.parse(costSummary);
const ingest = IngestRunList.parse(ingestRunList);
const evalRuns = EvalRunList.parse(evalRunList);
const fullRun = EvalRun.parse(evalRun);

function nth<T>(xs: readonly T[], i: number): T {
  const x = xs[i];
  if (x === undefined) throw new Error(`no element ${i}`);
  return x;
}

function variant(chunking: EvalRunSummary["config"]["chunking"], mode: EvalRunSummary["config"]["mode"], started: string, metrics: Partial<EvalRunSummary["metrics"]>): EvalRunSummary {
  const base = nth(evalRuns.runs, 0);
  return {
    ...base,
    run_id: `${chunking}-${mode}-${started}`,
    started_at: started,
    config: { ...base.config, chunking, mode },
    metrics: { ...base.metrics, ...metrics } as EvalRunSummary["metrics"],
  };
}

describe("bars and shares", () => {
  it("scales to the biggest bucket and never hides a non-zero count", () => {
    expect(barPercent(59, 59)).toBe(100);
    expect(barPercent(44, 59)).toBe(74.6);
    expect(barPercent(1, 100000)).toBe(0.5);
    expect(barPercent(0, 59)).toBe(0);
    expect(barPercent(5, 0)).toBe(0);
  });

  it("formats shares", () => {
    expect(sharePercent(35, 96)).toBe("36%");
    expect(sharePercent(1, 96)).toBe("1%");
    expect(sharePercent(1, 1000)).toBe("0.1%");
    expect(sharePercent(0, 96)).toBe("0%");
    expect(sharePercent(3, 0)).toBe("0%");
  });

  it("builds outcome rows from the CorpusStats fixture", () => {
    const rows = bucketRows(stats.by_outcome, humanise);
    expect(nth(rows, 0)).toEqual({ label: "inadmissible", count: 35, width: 100, share: "36%" });
    expect(rows.find((r) => r.label === "no violation")?.count).toBe(21);
    expect(rows.reduce((s, r) => s + r.count, 0)).toBe(stats.totals.documents);
  });

  it("labels a null chamber as (none)", () => {
    const rows = bucketRows(stats.by_chamber);
    expect(rows.find((r) => r.count === 15)?.label).toBe("(none)");
  });

  it("handles an empty breakdown", () => {
    expect(bucketRows([])).toEqual([]);
  });

  it("labels articles", () => {
    expect(articleLabel("8")).toBe("Art. 8");
    expect(articleLabel("P1-3")).toBe("Art. 3 of Protocol 1");
  });
});

describe("durations", () => {
  it("formats stage seconds", () => {
    expect(formatSeconds(0.396)).toBe("396 ms");
    expect(formatSeconds(1.53)).toBe("1.53 s");
    expect(formatSeconds(41.33)).toBe("41.3 s");
    expect(formatSeconds(103.4)).toBe("1 min 43 s");
    expect(formatSeconds(120)).toBe("2 min");
    expect(formatSeconds(0)).toBe("0 ms");
    expect(formatSeconds(-1)).toBe("–");
    expect(formatMs(233397.98)).toBe("3 min 53 s");
  });

  it("builds one bar per stage from the IngestRunList fixture", () => {
    const run = nth(ingest.runs, 0);
    const rows = stageRows(run);
    expect(rows.map((r) => r.stage)).toEqual(["download", "parse", "chunk", "embed", "index"]);
    expect(nth(rows, 0).width).toBe(100);
    expect(nth(rows, 0).label).toBe("1 min 43 s");
    expect(nth(rows, 1).width).toBeGreaterThan(0);
    expect(totalStageSeconds(run)).toBeCloseTo(148.956, 3);
    expect(rows.map((r) => r.share)).toEqual(["69%", "0.3%", "1.5%", "28%", "1%"]);
  });

  it("computes wall time", () => {
    const run = nth(ingest.runs, 0);
    expect(wallSeconds(run.started_at, run.finished_at)).toBe(149);
    expect(wallSeconds("nope", run.finished_at)).toBeNull();
    expect(wallSeconds(run.finished_at, run.started_at)).toBeNull();
  });

  it("formats timestamps", () => {
    expect(formatTimestamp("2026-11-03T16:38:51Z")).toBe("2026-11-03 16:38 UTC");
    expect(formatTimestamp("garbage")).toBe("garbage");
  });
});

describe("money and tokens", () => {
  it("keeps sub-cent amounts visible", () => {
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(0.0003146)).toBe("$0.0003");
    expect(formatUsd(0.00001)).toBe("<$0.0001");
    expect(formatUsd(0.0099)).toBe("$0.0099");
    expect(formatUsd(0.5880471)).toBe("$0.59");
    expect(formatUsd(1.6856)).toBe("$1.69");
    expect(formatUsd(Number.NaN)).toBe("–");
  });

  it("formats the CostSummary fixture", () => {
    expect(formatUsd(costs.total_usd)).toBe("$0.00");
    expect(costRequestCount(costs)).toBe(4);
    expect(formatTokens(nth(costs.by_purpose, 0).tokens_in)).toBe("4.4M");
    expect(formatTokens(950)).toBe("950");
    expect(formatTokens(12345)).toBe("12k");
  });
});

describe("eval table", () => {
  it("formats metrics, with a dash for null", () => {
    expect(formatMetric(0.07142857)).toBe("0.07");
    expect(formatMetric(0)).toBe("0.00");
    expect(formatMetric(null)).toBe("–");
    expect(formatMetric(undefined)).toBe("–");
  });

  it("builds a row from the EvalRunList fixture with null metrics intact", () => {
    const rows = buildEvalTable(evalRuns.runs);
    expect(rows).toHaveLength(1);
    expect(nth(rows, 0).chunking).toBe("recursive");
    expect(nth(rows, 0).metrics.faithfulness).toBeNull();
    expect(nth(rows, 0).best.faithfulness).toBe(false);
    expect(isAnswerLevel(nth(rows, 0))).toBe(false);
  });

  it("agrees with the full EvalRun fixture metrics", () => {
    expect(nth(buildEvalTable(evalRuns.runs), 0).metrics.mrr).toBe(fullRun.metrics.mrr);
  });

  it("orders by chunking then mode and picks the best per metric", () => {
    const runs = [
      variant("by_section", "hybrid", "2026-11-03T22:03:17Z", { mrr: 0.235, recall_at_5: 0.23, recall_at_10: 0.32 }),
      variant("fixed", "vector", "2026-11-03T21:57:16Z", { mrr: 0.2407, recall_at_5: 0.19, recall_at_10: 0.27 }),
      variant("fixed", "bm25", "2026-11-03T21:57:15Z", { mrr: 0.18, recall_at_5: 0.19, recall_at_10: 0.29 }),
      variant("recursive", "hybrid", "2026-11-03T21:58:26Z", { mrr: 0.225, faithfulness: 0.95, citation_accuracy: 0.95, neutrality: 1 }),
      variant("recursive", "hybrid_rerank", "2026-11-03T21:59:21Z", { mrr: 0.15, faithfulness: 0.95, citation_accuracy: 0.98, neutrality: 1 }),
    ];
    const rows = buildEvalTable(runs);
    expect(rows.map((r) => `${r.chunking}/${r.mode}`)).toEqual([
      "fixed/bm25",
      "fixed/vector",
      "recursive/hybrid",
      "recursive/hybrid_rerank",
      "by_section/hybrid",
    ]);
    const best = (key: MetricKey) =>
      rows.filter((r) => r.best[key]).map((r) => `${r.chunking}/${r.mode}`);
    expect(best("mrr")).toEqual(["fixed/vector"]);
    expect(best("recall_at_5")).toEqual(["by_section/hybrid"]);
    expect(best("recall_at_10")).toEqual(["by_section/hybrid"]);
    expect(best("faithfulness")).toEqual(["recursive/hybrid", "recursive/hybrid_rerank"]);
    expect(best("citation_accuracy")).toEqual(["recursive/hybrid_rerank"]);
    expect(best("neutrality")).toEqual(["recursive/hybrid", "recursive/hybrid_rerank"]);
    expect(isAnswerLevel(nth(rows, 2))).toBe(true);
  });

  it("keeps only the newest run per configuration", () => {
    const rows = buildEvalTable([
      variant("fixed", "bm25", "2026-11-01T00:00:00Z", { mrr: 0.9 }),
      variant("fixed", "bm25", "2026-11-02T00:00:00Z", { mrr: 0.1 }),
    ]);
    expect(rows).toHaveLength(1);
    expect(nth(rows, 0).metrics.mrr).toBe(0.1);
  });

  it("has no best for a metric nobody measured, and handles no runs", () => {
    const rows = buildEvalTable([variant("fixed", "bm25", "2026-11-01T00:00:00Z", {})]);
    expect(bestPerMetric(rows).faithfulness).toBeNull();
    expect(buildEvalTable([])).toEqual([]);
    expect(bestPerMetric([]).mrr).toBeNull();
  });

  it("treats values that round to the same two decimals as a tie", () => {
    const rows = buildEvalTable([
      variant("fixed", "bm25", "2026-11-01T00:00:00Z", { mrr: 0.2401 }),
      variant("fixed", "vector", "2026-11-01T00:00:00Z", { mrr: 0.2449 }),
    ]);
    expect(rows.filter((r) => r.best.mrr)).toHaveLength(2);
  });
});
