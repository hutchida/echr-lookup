import Link from "next/link";
import type { ApiResult } from "@/lib/api";
import type { EvalRunList } from "@echr/contract";
import { buildEvalTable, formatMetric, formatMs, formatUsd, humanise, isAnswerLevel, METRICS } from "../_lib/format";
import { Section, SectionError } from "./Section";

export function EvalSection({ result }: { result: ApiResult<EvalRunList> }) {
  if (!result.ok) {
    return (
      <Section id="eval-h" testId="stats-eval" title="Evaluation">
        <SectionError what="evaluation runs" error={result.error} status={result.status} />
      </Section>
    );
  }
  const rows = buildEvalTable(result.data.runs);
  if (rows.length === 0) {
    return (
      <Section id="eval-h" testId="stats-eval" title="Evaluation">
        <p className="text-sm text-stone-600">
          No evaluation runs yet. Run <code>pnpm eval:snapshot</code>.
        </p>
      </Section>
    );
  }
  const items = rows[0]?.run.item_count ?? 0;
  return (
    <Section
      id="eval-h"
      testId="stats-eval"
      title="Evaluation"
      note={`Newest run per chunking × search mode over ${items} questions. ★ marks the best value in each column; – means not measured for that run. ◆ marks runs where a model wrote answers and a judge scored them.`}
    >
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-stone-500">
            <tr>
              <th className="py-1 pr-3 font-medium">Chunking</th>
              <th className="py-1 pr-3 font-medium">Mode</th>
              {METRICS.map((m) => (
                <th key={m.key} className="py-1 pr-3 text-right font-medium" title={m.help}>
                  {m.label}
                </th>
              ))}
              <th className="py-1 pr-3 text-right font-medium">Cost</th>
              <th className="py-1 pr-3 text-right font-medium">Time</th>
              <th className="py-1 font-medium">Run</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.run.run_id} data-testid="eval-row" className="border-t border-stone-100">
                <td className="py-1 pr-3">{humanise(row.chunking)}</td>
                <td className="py-1 pr-3">
                  {humanise(row.mode)}
                  {isAnswerLevel(row) ? (
                    <span title="Answer-level run: a model wrote cited answers and a judge scored them"> ◆</span>
                  ) : null}
                </td>
                {METRICS.map((m) => (
                  <td key={m.key} className={`py-1 pr-3 text-right tabular-nums ${row.best[m.key] ? "font-semibold text-stone-900" : "text-stone-700"}`}>
                    {formatMetric(row.metrics[m.key])}
                    {row.best[m.key] ? (
                      <>
                        <span aria-hidden="true"> ★</span>
                        <span className="sr-only"> (best in column)</span>
                      </>
                    ) : null}
                  </td>
                ))}
                <td className="py-1 pr-3 text-right tabular-nums">{formatUsd(row.run.cost_usd)}</td>
                <td className="py-1 pr-3 text-right tabular-nums">{formatMs(row.run.timings_ms.total)}</td>
                <td className="py-1">
                  <Link href={`/stats/eval/${encodeURIComponent(row.run.run_id)}`} className="text-stone-700 underline underline-offset-2 hover:text-stone-900 focus-visible:outline-2 focus-visible:outline-offset-2">
                    per question
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="mt-4 grid gap-x-8 gap-y-1 text-xs text-stone-600 md:grid-cols-2">
        {METRICS.map((m) => (
          <div key={m.key}>
            <dt className="inline font-medium text-stone-800">{m.label}: </dt>
            <dd className="inline">{m.help}</dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}
