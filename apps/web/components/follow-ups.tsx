import Link from "next/link";
import type { Answer } from "@echr/contract";
import { followUpQuestions } from "./answer-display";
import { askHref } from "./demo-questions";

const MAX_QUESTION_CHARS = 500;

/**
 * Under an answer: a question field and two or three follow-up questions. Each is a plain link to a fresh
 * /ask?q=... (a new, standalone question): no thread, memory or previous question is kept anywhere.
 */
export function FollowUps({ answer }: { answer: Answer }) {
  const questions = followUpQuestions(answer);
  return (
    <section aria-labelledby="follow-ups-heading" data-testid="follow-ups" className="rounded-lg border border-stone-200 bg-white p-5">
      <h2 id="follow-ups-heading" className="text-sm font-medium uppercase tracking-wide text-stone-500">
        Ask next
      </h2>
      {questions.length > 0 ? (
        <ul className="mt-3 space-y-1.5 text-sm">
          {questions.map((q) => (
            <li key={q}>
              <Link href={askHref(q)} data-testid="follow-up" className="underline underline-offset-2 hover:text-stone-600">
                {q}
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
      <form action="/ask" method="get" className="mt-3 flex gap-2">
        <label htmlFor="ask-follow-up-input" className="sr-only">
          Ask another question
        </label>
        <input
          id="ask-follow-up-input"
          name="q"
          type="text"
          data-testid="ask-follow-up-input"
          maxLength={MAX_QUESTION_CHARS}
          required
          autoComplete="off"
          placeholder="Ask another question (each question is answered on its own)"
          className="min-w-0 flex-1 rounded-md border border-stone-300 bg-white px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-900"
        />
        <button
          type="submit"
          className="rounded-md bg-stone-900 px-4 py-2 text-sm font-medium text-white hover:bg-stone-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-900"
        >
          Ask
        </button>
      </form>
    </section>
  );
}
