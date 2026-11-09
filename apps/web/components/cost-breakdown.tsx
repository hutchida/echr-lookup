import type { Answer } from "@echr/contract";
import { formatCost, formatLatency, formatTokens, stepLabel } from "./answer-display";

/** What this answer cost: the total, then one row per pipeline step. */
export function CostBreakdown({ answer }: { answer: Answer }) {
  return (
    <section data-testid="answer-cost" aria-labelledby="cost-heading" className="rounded-lg border border-stone-200 bg-white p-5">
      <h2 id="cost-heading" className="text-sm font-medium uppercase tracking-wide text-stone-500">
        Cost of this answer
      </h2>
      <p className="mt-2 text-sm">
        <span className="text-2xl font-semibold tabular-nums">{formatCost(answer.total_cost_usd)}</span>
        <span className="ml-2 text-stone-600">
          in {formatLatency(answer.total_latency_ms)}
          {answer.models_used.length > 0 ? `, using ${answer.models_used.join(", ")}` : ", no model calls"}
        </span>
      </p>
      {answer.steps.length > 0 ? (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-stone-500">
              <tr>
                <th scope="col" className="py-1 pr-4 font-medium">Step</th>
                <th scope="col" className="py-1 pr-4 font-medium">Model</th>
                <th scope="col" className="py-1 pr-4 text-right font-medium">Tokens in / out (cached)</th>
                <th scope="col" className="py-1 pr-4 text-right font-medium">Time</th>
                <th scope="col" className="py-1 text-right font-medium">Cost</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {answer.steps.map((s) => (
                <tr key={s.step}>
                  <th scope="row" className="py-1.5 pr-4 font-normal">{stepLabel(s.step)}</th>
                  <td className="py-1.5 pr-4 text-stone-600">{s.model ?? "no model"}</td>
                  <td className="py-1.5 pr-4 text-right tabular-nums text-stone-600">
                    {s.model
                      ? `${formatTokens(s.tokens_in)} / ${formatTokens(s.tokens_out)} (${formatTokens(s.tokens_cached)})`
                      : "—"}
                  </td>
                  <td className="py-1.5 pr-4 text-right tabular-nums text-stone-600">{formatLatency(s.latency_ms)}</td>
                  <td className="py-1.5 text-right tabular-nums">{formatCost(s.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
