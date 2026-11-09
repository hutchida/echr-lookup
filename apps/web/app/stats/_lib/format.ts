import type { CostSummary, CountBucket, EvalRunSummary, IngestRun } from "./types";

/** Width of a bar in percent (0–100, one decimal). A non-zero count never rounds to an invisible bar. */
export function barPercent(value: number, max: number): number {
  if (!(max > 0) || !(value > 0)) return 0;
  const pct = Math.min(100, (value / max) * 100);
  return Math.max(0.5, Math.round(pct * 10) / 10);
}

/** "37%" style share of a total; "0%" when the total is zero. */
export function sharePercent(value: number, total: number): string {
  if (!(total > 0)) return "0%";
  const pct = (value / total) * 100;
  return `${pct >= 10 || pct === 0 ? Math.round(pct) : Math.round(pct * 10) / 10}%`;
}

export type BarRow = { label: string; count: number; width: number; share: string };

/** Turns API buckets into rows with a bar width relative to the biggest bucket. `key: null` becomes "(none)". */
export function bucketRows(buckets: readonly CountBucket[], labeller: (key: string) => string = (k) => k): BarRow[] {
  const max = Math.max(0, ...buckets.map((b) => b.count));
  const total = buckets.reduce((sum, b) => sum + b.count, 0);
  return buckets.map((b) => ({
    label: b.key === null ? "(none)" : labeller(b.key),
    count: b.count,
    width: barPercent(b.count, max),
    share: sharePercent(b.count, total),
  }));
}

/** `no_violation` → `no violation`. */
export const humanise = (key: string): string => key.replace(/_/g, " ");

/** Article keys are bare numbers ("8") or protocol articles ("P1-3"). */
export function articleLabel(key: string): string {
  const protocol = /^P(\d+)-(\w+)$/.exec(key);
  return protocol ? `Art. ${protocol[2]} of Protocol ${protocol[1]}` : `Art. ${key}`;
}

/** Seconds as a short human string: "396 ms", "41.3 s", "1 min 43 s". */
export function formatSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "–";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(2) : seconds.toFixed(1)} s`;
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
}

/** Milliseconds as seconds-style duration. */
export const formatMs = (ms: number): string => formatSeconds(ms / 1000);

/** Money with sub-cent amounts kept visible: $0.00, $0.0003, <$0.0001, $0.59, $1.69. */
export function formatUsd(usd: number): string {
  if (!Number.isFinite(usd) || usd < 0) return "–";
  if (usd === 0) return "$0.00";
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

export const formatCount = (n: number): string => n.toLocaleString("en-GB");

/** "4,433,340" → "4.4M" for token counts in tight table cells. */
export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  return formatCount(n);
}

/** ISO timestamp → "2026-11-03 16:38 UTC". */
export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

export type StageRow = { stage: string; seconds: number; label: string; width: number; share: string };

const STAGES = ["download", "parse", "chunk", "embed", "index"] as const;

/** One bar per ingestion stage; widths are relative to the slowest stage so even small stages are readable. */
export function stageRows(run: IngestRun): StageRow[] {
  const values = STAGES.map((stage) => ({ stage, seconds: run.stage_seconds[stage] }));
  const max = Math.max(0, ...values.map((v) => v.seconds));
  const total = values.reduce((sum, v) => sum + v.seconds, 0);
  return values.map((v) => ({
    ...v,
    label: formatSeconds(v.seconds),
    width: barPercent(v.seconds, max),
    share: sharePercent(v.seconds, total),
  }));
}

export function totalStageSeconds(run: IngestRun): number {
  return STAGES.reduce((sum, stage) => sum + run.stage_seconds[stage], 0);
}

/** Wall-clock length of a run from its timestamps, in seconds (null if unparsable). */
export function wallSeconds(startedAt: string, finishedAt: string): number | null {
  const ms = new Date(finishedAt).getTime() - new Date(startedAt).getTime();
  return Number.isFinite(ms) && ms >= 0 ? ms / 1000 : null;
}

export const costRequestCount = (cost: CostSummary): number => cost.by_purpose.reduce((sum, p) => sum + p.calls, 0);

// ---------------------------------------------------------------- eval table

export const CHUNKINGS = ["fixed", "recursive", "by_section"] as const;
export const MODES = ["bm25", "vector", "hybrid", "hybrid_rerank"] as const;

export const METRICS = [
  {
    key: "recall_at_5",
    label: "Recall@5",
    help: "Of the paragraphs a lawyer marked as the right evidence, the share that appear in the top 5 search hits.",
  },
  {
    key: "recall_at_10",
    label: "Recall@10",
    help: "The same, counted over the top 10 hits.",
  },
  {
    key: "mrr",
    label: "MRR",
    help: "Mean reciprocal rank: 1 divided by the position of the first correct hit (1st = 1.0, 2nd = 0.5, 10th = 0.1, none = 0), averaged over questions.",
  },
  {
    key: "faithfulness",
    label: "Faithfulness",
    help: "Share of claims in the generated answer that the cited paragraphs actually support (scored by a judge model). Answer-level runs only.",
  },
  {
    key: "citation_accuracy",
    label: "Citation acc.",
    help: "Share of citations whose quoted text is really in the cited paragraph and backs the claim. Answer-level runs only.",
  },
  {
    key: "neutrality",
    label: "Neutrality",
    help: "Share of politically loaded questions the answer handled evenly, without taking a side (judge-scored). Answer-level runs only.",
  },
] as const;

export type MetricKey = (typeof METRICS)[number]["key"];

export type EvalTableRow = {
  chunking: string;
  mode: string;
  run: EvalRunSummary;
  metrics: Record<MetricKey, number | null>;
  best: Record<MetricKey, boolean>;
};

/** Metric value for display: two decimals, an en dash when the run did not measure it. */
export const formatMetric = (value: number | null | undefined): string =>
  value === null || value === undefined || !Number.isFinite(value) ? "–" : value.toFixed(2);

/**
 * The best (highest) value per metric across rows, ignoring nulls. Ties all count as best.
 * Compared on the displayed two-decimal value so a visible tie is a tie. A metric no row measured has no best.
 */
export function bestPerMetric(rows: readonly { metrics: Record<MetricKey, number | null> }[]): Record<MetricKey, number | null> {
  const out = {} as Record<MetricKey, number | null>;
  for (const { key } of METRICS) {
    const values = rows.map((r) => r.metrics[key]).filter((v): v is number => v !== null && Number.isFinite(v));
    out[key] = values.length ? Math.max(...values.map((v) => Number(v.toFixed(2)))) : null;
  }
  return out;
}

/**
 * Chunking × mode table. When a configuration has several runs, the newest (by `started_at`, then list order) wins.
 * Rows follow CHUNKINGS × MODES order; configurations with no run are left out.
 */
export function buildEvalTable(runs: readonly EvalRunSummary[]): EvalTableRow[] {
  const latest = new Map<string, EvalRunSummary>();
  for (const run of runs) {
    const key = `${run.config.chunking}|${run.config.mode}`;
    const seen = latest.get(key);
    if (!seen || run.started_at > seen.started_at) latest.set(key, run);
  }
  const extraChunkings = [...new Set(runs.map((r) => r.config.chunking))].filter((c) => !(CHUNKINGS as readonly string[]).includes(c));
  const extraModes = [...new Set(runs.map((r) => r.config.mode))].filter((m) => !(MODES as readonly string[]).includes(m));
  const chunkings = [...CHUNKINGS, ...extraChunkings];
  const modes = [...MODES, ...extraModes];

  const rows: EvalTableRow[] = [];
  for (const chunking of chunkings) {
    for (const mode of modes) {
      const run = latest.get(`${chunking}|${mode}`);
      if (!run) continue;
      const metrics = Object.fromEntries(METRICS.map(({ key }) => [key, run.metrics[key]])) as Record<MetricKey, number | null>;
      rows.push({ chunking, mode, run, metrics, best: {} as Record<MetricKey, boolean> });
    }
  }
  const best = bestPerMetric(rows);
  for (const row of rows) {
    for (const { key } of METRICS) {
      const v = row.metrics[key];
      row.best[key] = v !== null && best[key] !== null && Number(v.toFixed(2)) === best[key];
    }
  }
  return rows;
}

/** True for rows where the model wrote answers (any generation-level metric present). */
export const isAnswerLevel = (row: EvalTableRow): boolean =>
  row.run.config.generator_model !== null ||
  row.metrics.faithfulness !== null ||
  row.metrics.citation_accuracy !== null ||
  row.metrics.neutrality !== null;
