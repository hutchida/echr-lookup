import Link from "next/link";
import type { Answer } from "@echr/contract";
import { ClaimBadge } from "./claim-badge";
import { CitationChip, DocTypeTag } from "./citation-chip";
import { AnswerText } from "./answer-text";
import { chipRef, displayQuote, segmentAnswer, statsCell, statsColumnLabel } from "./answer-display";

/** The stats route: the count, the rows behind it, the SQL that produced them, and the matching cases. */
export function StatsAnswer({ answer }: { answer: Answer }) {
  const stats = answer.stats;
  const byId = new Map(answer.citations.map((c) => [c.paragraph_id, c]));
  return (
    <>
      <section className="rounded-lg border border-stone-200 bg-white p-5">
        <h2 className="sr-only">Answer</h2>
        <AnswerText segments={segmentAnswer(answer).segments} />
        {stats ? (
          <p className="mt-4 text-sm">
            <span data-testid="stats-count" className="text-3xl font-semibold tabular-nums">{stats.count}</span>
            {stats.scope_total !== null ? (
              <span data-testid="stats-scope-total" className="ml-2 text-stone-600">
                of the {stats.scope_total} counted documents have the outcome asked about
              </span>
            ) : (
              <span className="ml-2 text-stone-600">matching documents</span>
            )}
          </p>
        ) : null}
        {stats?.explanation ? <p className="mt-2 text-sm text-stone-600">{stats.explanation}</p> : null}
      </section>

      {stats && stats.columns.length > 0 ? (
        <section className="rounded-lg border border-stone-200 bg-white p-5">
          <h2 className="text-sm font-medium uppercase tracking-wide text-stone-500">Rows from the query</h2>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-sm" data-testid="stats-rows">
              <thead className="text-xs uppercase tracking-wide text-stone-500">
                <tr>
                  {stats.columns.map((c) => (
                    <th key={c} scope="col" className="py-1 pr-4 font-medium">{statsColumnLabel(c)}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {stats.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => {
                      const shown = statsCell(stats.columns[j] ?? "", cell);
                      return (
                        <td key={j} className="py-1.5 pr-4 tabular-nums">
                          {shown.label}
                          {shown.key ? <code className="ml-2 font-mono text-xs text-stone-500">{shown.key}</code> : null}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {stats ? (
        <section className="rounded-lg border border-stone-200 bg-white p-5">
          <h2 className="text-sm font-medium uppercase tracking-wide text-stone-500">SQL used (read-only, over metadata)</h2>
          <pre data-testid="stats-sql" tabIndex={0} className="mt-3 overflow-x-auto rounded-md bg-stone-900 p-4 text-xs leading-6 text-stone-100">
            <code>{stats.sql}</code>
          </pre>
        </section>
      ) : null}

      {stats && stats.matching_cases.length > 0 ? (
        <section className="rounded-lg border border-stone-200 bg-white p-5">
          <h2 className="text-sm font-medium uppercase tracking-wide text-stone-500">
            Examples of matching cases ({stats.matching_cases.length} shown of {stats.count})
          </h2>
          <p className="mt-1 text-xs text-stone-500">
            Illustrations only: the count above comes from the SQL, not from these paragraphs.
          </p>
          <ul className="mt-3 space-y-3 text-sm">
            {stats.matching_cases.map((c) => (
              <li key={c.doc_id} data-testid="matching-case" data-doc-type={c.doc_type}>
                <Link href={`/case/${c.doc_id}`} className="font-medium underline underline-offset-2 hover:text-stone-600">
                  {c.case_name}
                </Link>
                <DocTypeTag docType={c.doc_type} />
                <span className="ml-2 text-xs text-stone-500">{c.doc_id}</span>
                {c.paragraph_id ? (
                  <blockquote className="mt-1 border-l-2 border-stone-300 pl-3 text-stone-700">
                    “{displayQuote(c.quote)}”{" "}
                    <Link href={c.link_target} className="whitespace-nowrap text-xs underline underline-offset-2">
                      {chipRef({ case_name: c.case_name, paragraph_id: c.paragraph_id })}
                    </Link>
                  </blockquote>
                ) : (
                  <p data-testid="matching-case-unquoted" className="mt-1 text-xs text-stone-500">
                    No paragraph of this case states the counted outcome, so none is quoted.
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {answer.claims.length > 0 ? (
        <section className="rounded-lg border border-stone-200 bg-white p-5">
          <h2 className="text-sm font-medium uppercase tracking-wide text-stone-500">Claims checked</h2>
          <ul className="mt-3 space-y-3 text-sm">
            {answer.claims.map((claim) => (
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
      ) : null}
    </>
  );
}
