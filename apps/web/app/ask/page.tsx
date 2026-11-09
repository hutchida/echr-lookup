import { Suspense } from "react";
import Link from "next/link";
import { ask, getStats } from "@/lib/api";
import { AnswerView } from "@/components/answer-view";
import { CorpusScope } from "@/components/corpus-scope";
import { FollowUps } from "@/components/follow-ups";
import { ErrorNotice } from "@/components/error-notice";
import { askHref, DEMO_QUESTIONS } from "@/components/demo-questions";

export const metadata = { title: "Ask · echr-lookup" };
export const dynamic = "force-dynamic";

const MAX_QUESTION_CHARS = 500;

type SearchParams = Promise<{ [key: string]: string | string[] | undefined }>;

async function AnswerPanel({ question }: { question: string }) {
  const result = await ask({ question });
  if (!result.ok) {
    return (
      <ErrorNotice
        title={result.status === null ? "Can’t reach the API" : "The API could not answer"}
        message={result.error}
        hint={
          result.status === null
            ? "Check that the API is running (pnpm dev:api) and that API_URL points at it."
            : "Nothing was guessed. Try again, or try a different question."
        }
      />
    );
  }
  return (
    <>
      <AnswerView answer={result.data} roundTripMs={result.ms} />
      <FollowUps answer={result.data} />
    </>
  );
}

/** What the library holds, from GET /stats; on failure it still says "UK cases only" but shows no numbers. */
async function CorpusLine() {
  const result = await getStats();
  return <CorpusScope stats={result.ok ? result.data : null} />;
}

function Thinking() {
  return (
    <div role="status" data-testid="ask-thinking" className="rounded-lg border border-stone-200 bg-white p-5 text-sm text-stone-700">
      <p className="font-medium motion-safe:animate-pulse">Thinking… (usually 5–10 s)</p>
      <p className="mt-1 text-stone-500">
        Finding the relevant paragraphs, writing cited claims, then checking each claim against its
        citation.
      </p>
    </div>
  );
}

export default async function AskPage({ searchParams }: { searchParams: SearchParams }) {
  const raw = (await searchParams).q;
  const q = (Array.isArray(raw) ? raw[0] : raw)?.trim() ?? "";

  return (
    <main className="mx-auto max-w-3xl space-y-6 px-6 py-10">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Ask</h1>
        <p className="mt-1 text-sm text-stone-600">
          Answers cite the exact paragraph and are checked against it. Counting questions are answered
          with SQL over the case metadata instead.
        </p>
        <Suspense fallback={<CorpusScope stats={null} />}>
          <CorpusLine />
        </Suspense>
      </div>

      <form action="/ask" method="get" className="space-y-3">
        <label htmlFor="ask-input" className="block text-sm font-medium">
          Your question
        </label>
        <div className="flex gap-2">
          <input
            id="ask-input"
            name="q"
            type="text"
            data-testid="ask-input"
            defaultValue={q}
            maxLength={MAX_QUESTION_CHARS}
            required
            autoComplete="off"
            placeholder="e.g. Does the Convention stop the UK deporting criminals?"
            className="min-w-0 flex-1 rounded-md border border-stone-300 bg-white px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-900"
          />
          <button
            type="submit"
            data-testid="ask-submit"
            className="rounded-md bg-stone-900 px-4 py-2 text-sm font-medium text-white hover:bg-stone-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-900"
          >
            Ask
          </button>
        </div>
      </form>

      <section aria-labelledby="examples-heading">
        <h2 id="examples-heading" className="text-xs font-medium uppercase tracking-wide text-stone-500">
          Try one of these
        </h2>
        <ul className="mt-2 space-y-1.5 text-sm">
          {DEMO_QUESTIONS.map((d) => (
            <li key={d.question}>
              <Link
                href={askHref(d.question)}
                data-testid="ask-example"
                className="underline underline-offset-2 hover:text-stone-600"
              >
                {d.question}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      {q ? (
        <section aria-live="polite" className="space-y-3">
          <h2 className="text-lg font-semibold tracking-tight">{q}</h2>
          <Suspense key={q} fallback={<Thinking />}>
            <AnswerPanel question={q} />
          </Suspense>
        </section>
      ) : null}
    </main>
  );
}
