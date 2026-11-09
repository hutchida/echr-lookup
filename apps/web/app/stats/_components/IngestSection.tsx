import type { ApiResult } from "@/lib/api";
import type { IngestRunList } from "@echr/contract";
import { formatCount, formatSeconds, formatTimestamp, stageRows, totalStageSeconds, wallSeconds } from "../_lib/format";
import { Section, SectionError, Stat } from "./Section";

export function IngestSection({ result }: { result: ApiResult<IngestRunList> }) {
  if (!result.ok) {
    return (
      <Section id="ingest-h" testId="stats-ingest" title="Ingestion">
        <SectionError what="ingestion runs" error={result.error} status={result.status} />
      </Section>
    );
  }
  const [last, ...older] = result.data.runs;
  if (!last) {
    return (
      <Section id="ingest-h" testId="stats-ingest" title="Ingestion">
        <p className="text-sm text-stone-600">
          No ingestion run recorded yet. Run <code>pnpm ingest:snapshot</code>.
        </p>
      </Section>
    );
  }
  const wall = wallSeconds(last.started_at, last.finished_at);
  return (
    <Section
      id="ingest-h"
      testId="stats-ingest"
      title="Ingestion"
      note={
        <>
          Last run <code>{last.run_id}</code> ({last.data_source}), finished {formatTimestamp(last.finished_at)}
          {wall !== null ? `, ${formatSeconds(wall)} wall time` : ""}. Embedder {last.embedder_model} ({last.embedding_dim} dimensions).
        </>
      }
    >
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-5">
        <Stat label="Seen" value={formatCount(last.counts.seen)} />
        <Stat label="Loaded (new)" value={formatCount(last.counts.new)} />
        <Stat label="Changed" value={formatCount(last.counts.changed)} />
        <Stat label="Skipped (unchanged)" value={formatCount(last.counts.unchanged_skipped)} />
        <Stat label="Failed" value={formatCount(last.counts.failed)} />
      </dl>

      <h3 className="mt-6 mb-2 text-sm font-medium text-stone-700">Time per stage (stages sum to {formatSeconds(totalStageSeconds(last))})</h3>
      <ul className="space-y-1">
        {stageRows(last).map((row) => (
          <li key={row.stage} data-testid={`stage-${row.stage}`} className="grid grid-cols-[6rem_1fr_9rem] items-center gap-2 text-sm">
            <span>{row.stage}</span>
            <span className="h-3 rounded-sm bg-stone-100" aria-hidden="true">
              <span className="block h-3 rounded-sm bg-stone-600" style={{ width: `${row.width}%` }} />
            </span>
            <span className="text-right tabular-nums">
              {row.label} <span className="text-stone-400">({row.share})</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-stone-500">Bar lengths are relative to the slowest stage; percentages are each stage’s share of the summed stage time.</p>

      {older.length > 0 ? (
        <>
          <h3 className="mt-6 mb-2 text-sm font-medium text-stone-700">Earlier runs</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-stone-500">
                <tr>
                  <th className="py-1 pr-4 font-medium">Run</th>
                  <th className="py-1 pr-4 font-medium">Finished</th>
                  <th className="py-1 pr-4 font-medium">Source</th>
                  <th className="py-1 pr-4 text-right font-medium">Seen</th>
                  <th className="py-1 pr-4 text-right font-medium">Failed</th>
                  <th className="py-1 text-right font-medium">Stage time</th>
                </tr>
              </thead>
              <tbody>
                {older.map((run) => (
                  <tr key={run.run_id} className="border-t border-stone-100">
                    <td className="py-1 pr-4 font-mono text-xs">{run.run_id}</td>
                    <td className="py-1 pr-4">{formatTimestamp(run.finished_at)}</td>
                    <td className="py-1 pr-4">{run.data_source}</td>
                    <td className="py-1 pr-4 text-right tabular-nums">{formatCount(run.counts.seen)}</td>
                    <td className="py-1 pr-4 text-right tabular-nums">{formatCount(run.counts.failed)}</td>
                    <td className="py-1 text-right tabular-nums">{formatSeconds(totalStageSeconds(run))}</td>
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
