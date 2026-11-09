import Link from "next/link";
import type { Answer } from "@echr/contract";
import { ClaimBadge } from "./claim-badge";
import { CitationChip, DocTypeTag } from "./citation-chip";
import { AnswerText } from "./answer-text";
import { CostBreakdown } from "./cost-breakdown";
import { StatsAnswer } from "./stats-answer";
import {
  answerFirstLayout,
  chipLabel,
  chipRef,
  claimStatusInfo,
  displayQuote,
  formatCost,
  formatLatency,
  isAnswerFirst,
  routeLabel,
  segmentAnswer,
} from "./answer-display";
import type { AnswerClaim } from "./answer-display";

function ClaimList({ title, claims, answer }: { title: string; claims: AnswerClaim[]; answer: Answer }) {
  if (claims.length === 0) return null;
  const byId = new Map(answer.citations.map((c) => [c.paragraph_id, c]));
  return (
    <section className="rounded-lg border border-stone-200 bg-white p-5">
      <h2 className="text-sm font-medium uppercase tracking-wide text-stone-500">{title}</h2>
      <ul className="mt-3 space-y-3 text-sm">
        {claims.map((claim) => (
          <li key={claim.id}>
            <p>
              {claim.text}
              {claim.citation_ids.flatMap((id) => byId.get(id) ?? []).map((c) => (
                <CitationChip key={c.paragraph_id} citation={c} />
              ))}
              <ClaimBadge claim={claim} />
            </p>
            {claim.reason ? <p className="mt-0.5 text-stone-600">Why: {claim.reason}</p> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Chips({ claim, answer }: { claim: AnswerClaim; answer: Answer }) {
  const byId = new Map(answer.citations.map((c) => [c.paragraph_id, c]));
  return (
    <>
      {claim.citation_ids.flatMap((id) => byId.get(id) ?? []).map((c) => (
        <CitationChip key={c.paragraph_id} citation={c} />
      ))}
      <ClaimBadge claim={claim} />
    </>
  );
}

/** Short answer first (large), then the evidence as points under neutral group headings. */
function AnswerFirstBody({ answer }: { answer: Answer }) {
  const { shortAnswer, groups, dropped } = answerFirstLayout(answer);
  const shown = answer.claims.filter((c) => c.status !== "unsupported");
  return (
    <>
      <div data-testid="answer" className="space-y-5">
        {shortAnswer ? (
          <section
            data-testid="short-answer"
            data-claim-id={shortAnswer.id}
            aria-labelledby="short-answer-heading"
            className="rounded-lg border-2 border-stone-900 bg-white p-6"
          >
            <h2 id="short-answer-heading" className="text-xs font-semibold uppercase tracking-wide text-stone-600">
              Short answer
            </h2>
            <p className="mt-2 text-xl font-medium leading-9">
              {shortAnswer.text}
              <Chips claim={shortAnswer} answer={answer} />
            </p>
          </section>
        ) : null}
        {groups.length > 0 ? (
          <section aria-labelledby="evidence-heading" className="rounded-lg border border-stone-200 bg-white p-5">
            <h2 id="evidence-heading" className="text-sm font-medium uppercase tracking-wide text-stone-500">
              The evidence
            </h2>
            <div className="mt-3 space-y-5">
              {groups.map((group, i) => (
                <div key={`${group.heading ?? "points"}-${i}`} data-testid="claim-group">
                  {group.heading ? <h3 className="text-base font-semibold text-stone-900">{group.heading}</h3> : null}
                  <ul className={`${group.heading ? "mt-2 " : ""}space-y-3 text-base leading-8`}>
                    {group.claims.map((claim) => (
                      <li key={claim.id} data-testid="claim" data-claim-id={claim.id}>
                        {claim.text}
                        <Chips claim={claim} answer={answer} />
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>
        ) : null}
        {shown.length > 0 ? (
          <details className="text-sm text-stone-700">
            <summary className="cursor-pointer font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-900">
              How each claim was checked
            </summary>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {shown.map((c) => (
                <li key={c.id}>
                  {c.role === "short_answer" ? "Short answer" : `Point ${c.id}`} ·{" "}
                  <span className="font-medium">{claimStatusInfo(c.status).label}</span>: {c.reason || "no reason given"}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
      <ClaimList title="Left out of the answer: failed verification" claims={dropped} answer={answer} />
      <SourceList answer={answer} />
    </>
  );
}

function SourceList({ answer }: { answer: Answer }) {
  if (answer.citations.length === 0) return null;
  return (
    <section aria-labelledby="sources-heading" className="rounded-lg border border-stone-200 bg-white p-5">
      <h2 id="sources-heading" className="text-sm font-medium uppercase tracking-wide text-stone-500">
        Sources
      </h2>
      <ol className="mt-3 space-y-3 text-sm">
        {answer.citations.map((c) => (
          <li key={c.paragraph_id} data-testid="source" data-doc-type={c.doc_type}>
            <Link href={c.link_target} aria-label={chipLabel(c)} className="font-medium underline underline-offset-2 hover:text-stone-600">
              {chipRef(c)}
            </Link>
            <DocTypeTag docType={c.doc_type} />
            <span className="ml-2 text-xs text-stone-500">{c.paragraph_id}</span>
            {c.doc_type === "legal_summary" ? (
              <p className="mt-0.5 text-xs text-amber-900">A summary written by the Court’s staff, not the judgment itself.</p>
            ) : null}
            <blockquote className="mt-1 border-l-2 border-stone-300 pl-3 text-stone-700">“{displayQuote(c.quote)}”</blockquote>
          </li>
        ))}
      </ol>
    </section>
  );
}

function RagBody({ answer }: { answer: Answer }) {
  const { segments, unplaced } = segmentAnswer(answer);
  const dropped = unplaced.filter((c) => c.status === "unsupported");
  const other = unplaced.filter((c) => c.status !== "unsupported");
  const placed = answer.claims.filter((c) => !unplaced.includes(c));
  return (
    <>
      <section className="rounded-lg border border-stone-200 bg-white p-5">
        <h2 className="sr-only">Answer</h2>
        <AnswerText segments={segments} />
        {placed.length > 0 ? (
          <details className="mt-4 text-sm text-stone-700">
            <summary className="cursor-pointer font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-900">
              How each claim was checked
            </summary>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {placed.map((c) => (
                <li key={c.id}>
                  <span className="font-medium">{claimStatusInfo(c.status).label}</span>: {c.reason || "no reason given"}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </section>
      <ClaimList title="Left out of the answer: failed verification" claims={dropped} answer={answer} />
      <ClaimList title="Other claims checked" claims={other} answer={answer} />
      <SourceList answer={answer} />
    </>
  );
}

function RefusedBody({ answer }: { answer: Answer }) {
  return (
    <section data-testid="answer-refused" className="rounded-lg border border-stone-300 bg-stone-100 p-5">
      <h2 className="text-sm font-medium uppercase tracking-wide text-stone-500">No answer from the sources</h2>
      <p data-testid="answer" className="mt-2 text-base leading-7">{answer.answer_text}</p>
      <p className="mt-3 text-sm text-stone-600">
        The indexed cases and statutes do not contain what is needed to answer this, so nothing was
        guessed. That does not mean the Court has never decided it: this library holds only United Kingdom cases,
        and may hold only a sample of them (see the line under the Ask heading). Try rewording the question,
        or ask about a specific Article or case.
      </p>
    </section>
  );
}

/** The whole answer card: route, timing, body (RAG / stats / refused), and its cost. */
export function AnswerView({ answer, roundTripMs }: { answer: Answer; roundTripMs?: number }) {
  const refused = answer.refused_or_not_in_sources && answer.route === "rag";
  return (
    <div className="space-y-5" data-testid="answer-view">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-stone-600">
        <span
          data-testid="answer-route"
          data-route={answer.route}
          className="rounded-md border border-stone-300 bg-white px-2 py-0.5 font-medium text-stone-800"
        >
          {routeLabel(answer.route)}
        </span>
        <span>Answered in {formatLatency(answer.total_latency_ms)}</span>
        {roundTripMs !== undefined ? <span>Page round trip {formatLatency(roundTripMs)}</span> : null}
        <span>Cost {formatCost(answer.total_cost_usd)}</span>
      </div>
      {refused ? (
        <RefusedBody answer={answer} />
      ) : answer.route === "stats" ? (
        <StatsAnswer answer={answer} />
      ) : isAnswerFirst(answer) ? (
        <AnswerFirstBody answer={answer} />
      ) : (
        <RagBody answer={answer} />
      )}
      <CostBreakdown answer={answer} />
    </div>
  );
}
