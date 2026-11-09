import { search } from "@/lib/api";
import { LabColumn, type ColumnContext } from "./_components/lab-column";
import { LabForm } from "./_components/lab-form";
import {
  COLUMNS,
  assignBadges,
  buildRequest,
  parseLabParams,
  rankMovements,
  ranksAcrossColumns,
  rerankDisabled,
  type ColumnKey,
  type SearchHit,
} from "./lab-model";

export const dynamic = "force-dynamic";
export const metadata = { title: "Lab · echr-lookup" };

export default async function LabPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = parseLabParams(await searchParams);
  const results = await Promise.all(COLUMNS.map((c) => search(buildRequest(params, c.mode))));
  const wallMs = Math.max(...results.map((r) => r.ms));

  const lists: Partial<Record<ColumnKey, SearchHit[]>> = {};
  COLUMNS.forEach((c, i) => {
    const r = results[i]!;
    if (r.ok) lists[c.key] = r.data.hits;
  });
  const reranked = results[3]!;
  const rerankReal = reranked.ok && !rerankDisabled(reranked.data);
  const ctx: ColumnContext = {
    badges: assignBadges(lists),
    ranks: ranksAcrossColumns(lists),
    movements: rerankReal ? rankMovements(lists.fused ?? [], lists.reranked ?? []) : new Map(),
  };
  const moves = [...ctx.movements.values()];
  const count = (kind: string) => moves.filter((m) => m.kind === kind).length;

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-3xl font-semibold tracking-tight">Lab: how retrieval works</h1>
      <p className="mt-2 max-w-3xl text-stone-600">
        One question, four ways of searching the same corpus. <strong>BM25</strong> matches words,{" "}
        <strong>vector search</strong> matches meaning, <strong>fusion</strong> merges the two lists by rank, and{" "}
        <strong>reranking</strong> has a second model re-read the best candidates. Each column below is that method’s own
        top {params.k}. A passage that shows up in more than one column carries the same lettered badge, so you can follow
        it across; the reranked column shows how far each passage moved from the fused order.
      </p>

      <LabForm params={params} />

      <p className="mt-4 text-xs text-stone-500" data-testid="lab-summary">
        “{params.q}” · chunking <strong>{params.chunking}</strong> · four searches run in parallel in {wallMs} ms
        {ctx.badges.size > 0 ? ` · ${ctx.badges.size} passages appear in more than one column (lettered badges)` : ""}
        {rerankReal
          ? ` · reranker vs fused: ${count("up")} up, ${count("down")} down, ${count("same")} unchanged, ${count("new")} new`
          : ""}
      </p>

      <p className="mt-2 text-xs text-stone-500">
        Under each passage, “Rank in other columns” gives its position in the other lists: #n if shown there, #n* if
        that method ranked it beyond the top {params.k}, – if it did not make that list.
      </p>

      <div className="mt-4 grid gap-5 md:grid-cols-2 xl:grid-cols-4">
        {COLUMNS.map((col, i) => (
          <LabColumn key={col.key} col={col} result={results[i]!} ctx={ctx} fusedHits={lists.fused} />
        ))}
      </div>
    </main>
  );
}
