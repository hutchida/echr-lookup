import Link from "next/link";
import { API_URL, getHealth } from "@/lib/api";
import { askHref, DEMO_QUESTIONS } from "@/components/demo-questions";

export const dynamic = "force-dynamic";

export default async function Home() {
  const result = await getHealth();

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">echr-lookup</h1>
      <p className="mt-2 text-stone-600">
        Ask questions of UK case law at the European Court of Human Rights. Every claim cites the
        exact paragraph, and every citation is checked against it.
      </p>

      <section aria-labelledby="demo-heading" className="mt-8">
        <h2 id="demo-heading" className="text-sm font-medium uppercase tracking-wide text-stone-500">
          Start with a question
        </h2>
        <ul className="mt-3 space-y-2 text-sm">
          {DEMO_QUESTIONS.map((d) => (
            <li key={d.question}>
              <Link href={askHref(d.question)} data-testid="home-demo-question" className="underline underline-offset-2 hover:text-stone-600">
                {d.question}
              </Link>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-sm text-stone-600">
          Or look under the hood: the <Link href="/lab" className="underline underline-offset-2 hover:text-stone-900">Lab</Link>{" "}
          compares four ways of searching the same query, and{" "}
          <Link href="/stats" className="underline underline-offset-2 hover:text-stone-900">Stats</Link> shows the
          corpus, ingestion runs, evaluation results and what the app has cost.
        </p>
      </section>

      <section className="mt-10 rounded-lg border border-stone-200 bg-white p-5">
        <h2 className="text-sm font-medium uppercase tracking-wide text-stone-500">API status</h2>
        {result.ok ? (
          <dl className="mt-3 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-sm">
            <dt className="text-stone-500">Status</dt>
            <dd data-testid="api-status">{result.health.status}</dd>
            <dt className="text-stone-500">Database</dt>
            <dd>
              {result.health.db.reachable
                ? `reachable (${result.health.db.extensions.join(", ")})`
                : "unreachable"}
            </dd>
            <dt className="text-stone-500">Data source</dt>
            <dd>{result.health.data_source}</dd>
            <dt className="text-stone-500">Round trip</dt>
            <dd>{result.ms} ms</dd>
          </dl>
        ) : (
          <p className="mt-3 text-sm text-red-700" data-testid="api-status">
            Can’t reach the API at {API_URL}: {result.error}. Start it with <code>pnpm dev</code>.
          </p>
        )}
      </section>
    </main>
  );
}
