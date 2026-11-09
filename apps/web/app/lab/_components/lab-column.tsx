import type { SearchResult } from "@echr/contract";
import type { ApiResult } from "@/lib/api";
import {
  COLUMNS,
  droppedByRerank,
  paragraphLink,
  rerankDisabled,
  scoreOf,
  snippet,
  timingText,
  type ChunkBadge,
  type ColumnKey,
  type RankInfo,
  type Movement,
  type SearchHit,
} from "../lab-model";

type Column = (typeof COLUMNS)[number];

export type ColumnContext = {
  badges: Map<string, ChunkBadge>;
  ranks: Map<string, Partial<Record<ColumnKey, RankInfo>>>;
  movements: Map<string, Movement>;
};

const SHORT: Record<ColumnKey, string> = { bm25: "BM25", vector: "Vector", fused: "Fused", reranked: "Reranked" };

function Badge({ badge }: { badge: ChunkBadge | undefined }) {
  if (!badge) {
    return (
      <span
        className="inline-flex h-6 min-w-6 items-center justify-center rounded px-1 text-[11px] text-stone-400 ring-1 ring-stone-200"
        title="This passage appears in only this column"
        data-testid="lab-badge-solo"
      >
        –
      </span>
    );
  }
  const where = badge.columns.map((c) => SHORT[c]).join(", ");
  return (
    <span
      className={`inline-flex h-6 min-w-6 items-center justify-center rounded px-1 text-xs font-bold ring-2 ${badge.color}`}
      title={`Same passage in: ${where}`}
      aria-label={`Passage ${badge.letter}, also in: ${where}`}
      data-testid="lab-badge"
      data-chunk-letter={badge.letter}
    >
      {badge.letter}
    </span>
  );
}

function MovementTag({ movement }: { movement: Movement | undefined }) {
  if (!movement) return null;
  const style =
    movement.kind === "up"
      ? "bg-emerald-50 text-emerald-800 ring-emerald-300"
      : movement.kind === "down"
        ? "bg-rose-50 text-rose-800 ring-rose-300"
        : movement.kind === "new"
          ? "bg-violet-50 text-violet-800 ring-violet-300"
          : "bg-stone-50 text-stone-600 ring-stone-200";
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ${style}`}
      data-testid="lab-movement"
      data-movement={movement.kind}
      title="Change of rank from the fused column to this reranked column"
    >
      {movement.text}
    </span>
  );
}

function HitCard({ col, hit, ctx }: { col: Column; hit: SearchHit; ctx: ColumnContext }) {
  const score = scoreOf(col.key, hit);
  const badge = ctx.badges.get(hit.chunk.id);
  const ranks = ctx.ranks.get(hit.chunk.id) ?? {};
  const others = COLUMNS.filter((c) => c.key !== col.key);
  return (
    <li className="rounded-md border border-stone-200 bg-white p-3" data-testid="lab-hit" data-chunk-id={hit.chunk.id}>
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold tabular-nums text-stone-700">#{hit.rank}</span>
        <Badge badge={badge} />
        {col.key === "reranked" ? <MovementTag movement={ctx.movements.get(hit.chunk.id)} /> : null}
        <span className="ml-auto text-right text-xs text-stone-600">
          <span className="tabular-nums font-medium text-stone-900">{score.text}</span>
          <span className="block text-[10px] uppercase tracking-wide text-stone-500">{score.label}</span>
        </span>
      </div>
      <p className="mt-2 text-sm font-medium leading-snug">{hit.case_name}</p>
      <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-stone-600">
        {hit.paragraph_ids.map((pid) => {
          const link = paragraphLink(pid);
          return (
            <a
              key={pid}
              href={link.href}
              className="rounded bg-stone-100 px-1.5 py-0.5 font-mono text-[11px] text-stone-800 underline decoration-stone-300 hover:bg-stone-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-600"
              title={pid}
            >
              §{link.ref}
            </a>
          );
        })}
        <span className="rounded bg-stone-100 px-1.5 py-0.5 text-[11px]" title="Chunking strategy of this passage">
          {hit.chunk.strategy}
        </span>
      </p>
      <p className="mt-2 text-xs leading-relaxed text-stone-600">{snippet(hit.chunk.text)}</p>
      <p className="mt-2 text-[11px] leading-snug text-stone-500" data-testid="lab-also-in">
        Rank in other columns:{" "}
        {others.map((c, i) => {
          const r = ranks[c.key];
          return (
            <span key={c.key} title={r && !r.shown ? "Outside the top k shown in that column" : undefined}>
              {i ? " · " : ""}
              {SHORT[c.key]} {r ? `#${r.rank}${r.shown ? "" : "*"}` : "–"}
            </span>
          );
        })}
      </p>
    </li>
  );
}

export function LabColumn({
  col,
  result,
  ctx,
  fusedHits,
}: {
  col: Column;
  result: ApiResult<SearchResult>;
  ctx: ColumnContext;
  fusedHits?: SearchHit[];
}) {
  const disabled = col.key === "reranked" && result.ok && rerankDisabled(result.data);
  const dropped = col.key === "reranked" && result.ok && !disabled && fusedHits ? droppedByRerank(fusedHits, result.data.hits) : [];
  return (
    <section className="min-w-0" data-testid={`lab-column-${col.key}`} aria-labelledby={`lab-h-${col.key}`}>
      <h2 id={`lab-h-${col.key}`} className="text-base font-semibold tracking-tight">
        {col.title}
      </h2>
      <p className="mt-1 min-h-[7.5rem] text-xs leading-relaxed text-stone-600" data-testid="lab-explain">
        <span className="font-medium text-stone-800">What you’re seeing: </span>
        {col.explain}
      </p>
      {result.ok ? (
        <>
          <p className="mt-2 text-[11px] text-stone-500" data-testid="lab-timing">
            {timingText(col.key, result.data)} · round trip {result.ms} ms
          </p>
          {disabled ? (
            <p className="mt-2 rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900" role="status">
              Reranking is switched off on this API (RERANK_ENABLED=0), so this column simply repeats the fused order.
            </p>
          ) : null}
          {result.data.hits.length === 0 ? (
            <p className="mt-3 rounded border border-stone-200 bg-white p-3 text-sm text-stone-600">
              No passages matched.
            </p>
          ) : (
            <ol className="mt-3 space-y-2">
              {result.data.hits.map((hit) => (
                <HitCard key={hit.chunk.id} col={col} hit={hit} ctx={ctx} />
              ))}
            </ol>
          )}
          {dropped.length > 0 ? (
            <p className="mt-3 text-xs text-stone-600" data-testid="lab-dropped">
              Dropped from the fused top {fusedHits?.length}: {dropped.map((h) => `#${h.rank} ${h.case_name}`).join("; ")}.
            </p>
          ) : null}
        </>
      ) : (
        <div className="mt-3 rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900" role="alert" data-testid="lab-error">
          <p className="font-medium">This search failed.</p>
          <p className="mt-1 break-words text-xs">
            {result.error}
            {result.status ? ` (HTTP ${result.status})` : ""}
          </p>
          {result.status === null ? (
            <p className="mt-1 text-xs">Could not reach the API. Is it running, and is API_URL right?</p>
          ) : null}
        </div>
      )}
    </section>
  );
}
