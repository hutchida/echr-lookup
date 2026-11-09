import Link from "next/link";
import { getEvalRun } from "@/lib/api";
import { formatMetric, formatMs, formatTimestamp, formatUsd, humanise } from "../../_lib/format";
import { SectionError } from "../../_components/Section";

export const dynamic = "force-dynamic";

export default async function EvalRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = await getEvalRun(id);

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <p className="text-sm">
        <Link href="/stats#eval-h" className="text-stone-600 underline underline-offset-2 hover:text-stone-900">
          ← Stats
        </Link>
      </p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight">Eval run</h1>
      {!result.ok ? (
        <div className="mt-6">
          <SectionError what={`eval run ${id}`} error={result.error} status={result.status} />
        </div>
      ) : (
        <>
          <p className="mt-1 text-stone-600">
            <code>{result.data.run_id}</code> · {humanise(result.data.config.chunking)} chunking · {humanise(result.data.config.mode)} · started{" "}
            {formatTimestamp(result.data.started_at)} · {formatMs(result.data.timings_ms.total)} total · {formatUsd(result.data.cost_usd)}
          </p>
          <div className="mt-6 overflow-x-auto rounded-lg border border-stone-200 bg-white p-5" data-testid="eval-items">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-stone-500">
                <tr>
                  <th className="py-1 pr-3 font-medium">Question id</th>
                  <th className="py-1 pr-3 text-right font-medium">Recall@5</th>
                  <th className="py-1 pr-3 text-right font-medium">Recall@10</th>
                  <th className="py-1 pr-3 text-right font-medium">Reciprocal rank</th>
                  <th className="py-1 pr-3 text-right font-medium">Faithfulness</th>
                  <th className="py-1 pr-3 text-right font-medium">Citation acc.</th>
                  <th className="py-1 pr-3 text-right font-medium">Neutrality</th>
                  <th className="py-1 pr-3 text-right font-medium">Latency</th>
                  <th className="py-1 font-medium">Top hit</th>
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((item) => (
                  <tr key={item.item_id} className="border-t border-stone-100">
                    <td className="py-1 pr-3 font-mono text-xs">{item.item_id}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{formatMetric(item.recall_at_5)}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{formatMetric(item.recall_at_10)}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{formatMetric(item.reciprocal_rank)}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{formatMetric(item.faithfulness)}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{formatMetric(item.citation_accuracy)}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{formatMetric(item.neutrality)}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{formatMs(item.latency_ms)}</td>
                    <td className="py-1 font-mono text-xs">
                      {item.retrieved_paragraph_ids[0] ? (
                        <Link
                          href={`/case/${item.retrieved_paragraph_ids[0].split("§")[0]}#p${item.retrieved_paragraph_ids[0].split("§")[1] ?? ""}`}
                          className="underline underline-offset-2"
                        >
                          {item.retrieved_paragraph_ids[0]}
                        </Link>
                      ) : (
                        "–"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {result.data.items.length === 0 ? <p className="mt-2 text-sm text-stone-600">This run has no per-question results.</p> : null}
          </div>
        </>
      )}
    </main>
  );
}
