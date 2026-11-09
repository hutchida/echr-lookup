import type { ApiResult } from "@/lib/api";
import type { CostSummary } from "@echr/contract";
import { costRequestCount, formatCount, formatMs, formatTimestamp, formatTokens, formatUsd } from "../_lib/format";
import { Section, SectionError, Stat } from "./Section";

type Row = { name: string; calls: number; tokens_in: number; tokens_out: number; cost_usd: number };

function UsageTable({ title, rows }: { title: string; rows: Row[] }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-medium text-stone-700">{title}</h3>
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-stone-500">
          <tr>
            <th className="py-1 pr-3 font-medium">Name</th>
            <th className="py-1 pr-3 text-right font-medium">Calls</th>
            <th className="py-1 pr-3 text-right font-medium">Tokens in</th>
            <th className="py-1 pr-3 text-right font-medium">Tokens out</th>
            <th className="py-1 text-right font-medium">Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name} className="border-t border-stone-100">
              <td className="py-1 pr-3">{r.name}</td>
              <td className="py-1 pr-3 text-right tabular-nums">{formatCount(r.calls)}</td>
              <td className="py-1 pr-3 text-right tabular-nums">{formatTokens(r.tokens_in)}</td>
              <td className="py-1 pr-3 text-right tabular-nums">{formatTokens(r.tokens_out)}</td>
              <td className="py-1 text-right tabular-nums">{formatUsd(r.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CostSection({ result }: { result: ApiResult<CostSummary> }) {
  if (!result.ok) {
    return (
      <Section id="costs-h" testId="stats-costs" title="Cost">
        <SectionError what="costs" error={result.error} status={result.status} />
      </Section>
    );
  }
  const c = result.data;
  return (
    <Section
      id="costs-h"
      testId="stats-costs"
      title="Cost"
      note="Runtime calls the app made (embedding, answers, citation checks, eval judge) since the last database reset, logged one row per call in cost_log. Local models (embedding, reranking) cost $0."
    >
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Total spent" value={<span data-testid="cost-total">{formatUsd(c.total_usd)}</span>} />
        <Stat label="Requests" value={formatCount(costRequestCount(c))} />
        <Stat label="Since" value={<span className="text-base">{c.since ? formatTimestamp(c.since) : "no calls yet"}</span>} />
      </dl>
      {c.by_purpose.length === 0 ? (
        <p className="mt-4 text-sm text-stone-600">No calls logged yet.</p>
      ) : (
        <div className="mt-6 grid gap-8 md:grid-cols-2">
          <UsageTable title="By purpose" rows={c.by_purpose.map((p) => ({ ...p, name: p.purpose }))} />
          <UsageTable title="By model" rows={c.by_model.map((m) => ({ ...m, name: m.model }))} />
        </div>
      )}
      {c.recent.length > 0 ? (
        <>
          <h3 className="mt-6 mb-2 text-sm font-medium text-stone-700">Most recent calls</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-stone-500">
                <tr>
                  <th className="py-1 pr-3 font-medium">When</th>
                  <th className="py-1 pr-3 font-medium">Purpose</th>
                  <th className="py-1 pr-3 font-medium">Model</th>
                  <th className="py-1 pr-3 text-right font-medium">Tokens in/out</th>
                  <th className="py-1 pr-3 text-right font-medium">Latency</th>
                  <th className="py-1 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {c.recent.slice(0, 8).map((e) => (
                  <tr key={e.id} className="border-t border-stone-100">
                    <td className="py-1 pr-3">{formatTimestamp(e.timestamp)}</td>
                    <td className="py-1 pr-3">{e.purpose}</td>
                    <td className="py-1 pr-3">{e.model}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">
                      {formatTokens(e.tokens_in)} / {formatTokens(e.tokens_out)}
                    </td>
                    <td className="py-1 pr-3 text-right tabular-nums">{formatMs(e.latency_ms)}</td>
                    <td className="py-1 text-right tabular-nums">{formatUsd(e.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </Section>
  );
}
