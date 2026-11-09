import Link from "next/link";
import type { CorpusStats } from "@echr/contract";

const CASE_DOC_TYPES: Record<string, string> = {
  judgment: "judgments",
  decision: "decisions",
  communicated: "communicated cases",
  legal_summary: "legal summaries",
};

export type CorpusScopeText = {
  /** "98 documents" when the stats call worked; null otherwise (never a guessed number). */
  size: string | null;
  /** What the library holds, in plain words. */
  scope: string;
  /** Only for the snapshot: the warning that a refused question may still have been decided by the Court. */
  sample: string | null;
};

const fmt = (n: number) => n.toLocaleString("en-GB");

/**
 * The Ask page's statement of what it searches, from GET /stats (the same source as the Stats page). Without stats
 * it still says the library is UK cases only, but gives no numbers.
 */
export function corpusScope(stats: CorpusStats | null): CorpusScopeText {
  if (!stats) {
    return { size: null, scope: "United Kingdom cases at the European Court of Human Rights only.", sample: null };
  }
  const by = new Map(stats.by_doc_type.map((b) => [String(b.key), b.count]));
  const kinds = Object.entries(CASE_DOC_TYPES)
    .filter(([key]) => (by.get(key) ?? 0) > 0)
    .map(([, label]) => label);
  const legislation = by.get("legislation") ?? 0;
  const kindsText = kinds.length > 1 ? `${kinds.slice(0, -1).join(", ")} and ${kinds.at(-1)}` : (kinds[0] ?? "");
  let scope = "United Kingdom cases at the European Court of Human Rights only";
  if (kindsText) scope += ` (${kindsText})`;
  if (legislation > 0) scope += `, plus ${fmt(legislation)} legislation ${legislation === 1 ? "text" : "texts"}`;
  return {
    size: `${fmt(stats.totals.documents)} ${stats.totals.documents === 1 ? "document" : "documents"}`,
    scope: `${scope}.`,
    sample:
      stats.data_source === "snapshot"
        ? "This is the small committed sample, not the full HUDOC download: when it has no answer, the Court may still have decided the question in a case that is not here."
        : null,
  };
}

/** One line under the Ask lede: how big the library is, what it holds, and a link to the Stats page. */
export function CorpusScope({ stats }: { stats: CorpusStats | null }) {
  const t = corpusScope(stats);
  return (
    <p data-testid="corpus-scope" className="mt-2 rounded-md border border-stone-200 bg-white px-3 py-2 text-sm text-stone-700">
      <span className="font-medium">Searching </span>
      {t.size ? <span data-testid="corpus-size">{t.size}: </span> : null}
      {t.scope}
      {t.sample ? <span data-testid="corpus-sample"> {t.sample}</span> : null}{" "}
      <Link href="/stats" className="whitespace-nowrap underline underline-offset-2 hover:text-stone-600">
        What’s in it →
      </Link>
    </p>
  );
}
