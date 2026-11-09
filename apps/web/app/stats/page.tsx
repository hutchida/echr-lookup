import { getCosts, getEvalRuns, getIngestRuns, getStats } from "@/lib/api";
import { CorpusSection } from "./_components/CorpusSection";
import { CostSection } from "./_components/CostSection";
import { EvalSection } from "./_components/EvalSection";
import { IngestSection } from "./_components/IngestSection";

export const dynamic = "force-dynamic";
export const metadata = { title: "Stats · echr-lookup" };

export default async function StatsPage() {
  const [stats, ingest, costs, evals] = await Promise.all([getStats(), getIngestRuns(), getCosts(), getEvalRuns()]);

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Stats</h1>
      <p className="mt-1 text-stone-600">What is in the corpus, how the last ingestion went, what the app has cost, and how well search and answers score.</p>
      <div className="mt-8 space-y-6">
        <CorpusSection result={stats} />
        <IngestSection result={ingest} />
        <CostSection result={costs} />
        <EvalSection result={evals} />
      </div>
    </main>
  );
}
