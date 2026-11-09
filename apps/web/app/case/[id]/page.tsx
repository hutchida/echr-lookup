import Link from "next/link";
import { notFound } from "next/navigation";
import { getCase } from "@/lib/api";
import { ErrorNotice } from "@/components/error-notice";
import { HighlightTarget } from "@/components/highlight-target";
import {
  articlesLabel,
  caseTitle,
  docTypeLabel,
  groupBySection,
  importanceLabel,
  outcomeLabel,
  paragraphDomId,
  paragraphLabel,
} from "@/components/case-display";

export const dynamic = "force-dynamic";

type Params = Promise<{ id: string }>;

export async function generateMetadata({ params }: { params: Params }) {
  return { title: `${decodeURIComponent((await params).id)} · echr-lookup` };
}

export default async function CasePage({ params }: { params: Params }) {
  const id = decodeURIComponent((await params).id);
  const result = await getCase(id);

  if (!result.ok) {
    if (result.status === 404) notFound();
    return (
      <main className="mx-auto max-w-3xl space-y-4 px-6 py-10">
        <ErrorNotice
          testId="case-error"
          title="Couldn’t load this case"
          message={result.error}
          hint="Check that the API is running (pnpm dev:api) and that API_URL points at it."
        />
        <p className="text-sm">
          <Link href="/ask" className="underline underline-offset-2">Back to Ask</Link>
        </p>
      </main>
    );
  }

  const { document: doc, paragraphs } = result.data;
  const groups = groupBySection(paragraphs);
  const facts: [string, string][] = [
    ["Date", doc.date],
    ["Type", docTypeLabel(doc.doc_type)],
    ["Chamber", doc.chamber ?? "—"],
    ["Articles", articlesLabel(doc.articles)],
    ["Outcome", outcomeLabel(doc.outcome)],
    ["Importance", importanceLabel(doc.importance)],
    ["ECLI", doc.ecli ?? "—"],
  ];

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <HighlightTarget />
      <header data-testid="case-header" className="rounded-lg border border-stone-200 bg-white p-5">
        <h1 className="text-2xl font-semibold tracking-tight">{caseTitle(doc.case_name)}</h1>
        <dl className="mt-4 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-sm">
          {facts.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-stone-500">{k}</dt>
              <dd className="break-words">{v}</dd>
            </div>
          ))}
          <dt className="text-stone-500">Source</dt>
          <dd>
            <a href={doc.source_url} target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-stone-600">
              Open {doc.item_id} on HUDOC<span className="sr-only"> (opens in a new tab)</span> ↗
            </a>
          </dd>
        </dl>
        <p className="mt-3 text-xs text-stone-500">{paragraphs.length} paragraphs, in document order.</p>
      </header>

      {groups.map((g, gi) => (
        <section key={`${g.section}-${gi}`} aria-labelledby={`section-${gi}`} className="mt-8">
          <h2 id={`section-${gi}`} className="text-sm font-medium uppercase tracking-wide text-stone-500">
            {g.section}
          </h2>
          <div className="mt-3 space-y-1">
            {g.paragraphs.map((p) => {
              const domId = paragraphDomId(p.id);
              return (
                <div
                  key={p.id}
                  id={domId}
                  data-testid="case-paragraph"
                  data-paragraph-id={p.id}
                  className="group grid scroll-mt-24 grid-cols-[3.5rem_1fr] gap-x-2 rounded-md border-l-4 border-transparent px-2 py-2 target:border-amber-500 target:bg-amber-100 data-[highlighted=true]:border-amber-500 data-[highlighted=true]:bg-amber-100"
                >
                  <a
                    href={`#${domId}`}
                    aria-label={`Link to paragraph ${paragraphLabel(p)}`}
                    className="text-right text-sm tabular-nums text-stone-500 hover:text-stone-900 focus-visible:outline-2 focus-visible:outline-stone-900"
                  >
                    {paragraphLabel(p)}
                  </a>
                  <p className="whitespace-pre-line text-[15px] leading-7">
                    <span className="mr-2 hidden rounded bg-amber-500 px-1.5 py-0.5 text-xs font-semibold text-white group-target:inline group-data-[highlighted=true]:inline">
                      Cited paragraph
                    </span>
                    {p.text}
                  </p>
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </main>
  );
}
