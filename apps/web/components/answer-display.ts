import type { Answer, Citation } from "@echr/contract";
import { docTypeLabel, outcomeLabel, paragraphRef } from "./case-display";

export { paragraphDomId, paragraphRef } from "./case-display";

export type AnswerClaim = Answer["claims"][number];
export type AnswerStep = Answer["steps"][number];

/** One piece of the rendered answer, in reading order. */
export type Segment =
  | { kind: "text"; text: string }
  /** A claim as the model wrote it, its citation chips, and whether the sentence ended with a full stop. */
  | { kind: "claim"; claim: AnswerClaim; text: string; citations: Citation[]; endsSentence: boolean }
  /** A citation marker found in plain text (no claim attached), e.g. the fixture's `[001-57619§91]`. */
  | { kind: "cite"; citations: Citation[] };

export type SegmentedAnswer = {
  segments: Segment[];
  /** Claims whose text is not part of `answer_text` (dropped as unsupported, or stats claims). */
  unplaced: AnswerClaim[];
};

/** `SOERING v. THE UNITED KINGDOM` -> `Soering v UK` (mirrors the API's inline-marker names). */
export function shortCaseName(caseName: string, maxChars = 40): string {
  let name = caseName.trim().replace(/^CASE OF\s+/i, "");
  name = name.replace(/\[[^\]]*\]|\([^)]*\)/g, "");
  name = name.replace(/\bthe united kingdom\b/gi, "UK").replace(/\bv\./g, "v");
  const letters = [...name].filter((c) => /\p{L}/u.test(c));
  if (letters.length > 0 && letters.filter((c) => c === c.toUpperCase() && c !== c.toLowerCase()).length / letters.length > 0.6) {
    name = name
      .split(/\s+/)
      .map((w) => {
        if (w === "UK" || w === "v") return w;
        if (w === "V" || w === "AND") return w.toLowerCase();
        if (/^(?:[A-Z]\.)+[A-Z]?\.?$/.test(w)) return w;
        return w
          .split("-")
          .map((p) => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase())
          .join("-");
      })
      .join(" ");
  }
  name = name.replace(/\s+/g, " ").trim();
  return name.length <= maxChars ? name : `${name.slice(0, maxChars - 1).trimEnd()}…`;
}

/** Short label for the kind of document a citation comes from. A legal summary must never pass for the judgment. */
export const DOC_TYPE_SHORT: Record<Citation["doc_type"], string> = {
  judgment: "Judgment",
  decision: "Decision",
  communicated: "Communicated case",
  legal_summary: "Legal summary",
  legislation: "Legislation",
};

export function docTypeShortLabel(docType: Citation["doc_type"]): string {
  return DOC_TYPE_SHORT[docType] ?? docType;
}

/** The case and paragraph on a citation chip: `Soering v UK §88`. */
export function chipRef(c: Pick<Citation, "case_name" | "paragraph_id">): string {
  return `${shortCaseName(c.case_name)} §${paragraphRef(c.paragraph_id)}`;
}

/** The full text of a citation chip, with the document type: `Soering v UK §88 · Judgment`. */
export function chipLabel(c: Pick<Citation, "case_name" | "paragraph_id" | "doc_type">): string {
  return `${chipRef(c)} · ${docTypeShortLabel(c.doc_type)}`;
}

const BRACKET = /\[([^[\]]*§[^[\]]*)\]/g;
const TRAILING_MARKERS = /(?:\s*\[[^[\]]*§[^[\]]*\])*(\.?)/y;

function resolveBracket(inner: string, citations: Citation[]): Citation[] {
  const found: Citation[] = [];
  let currentName = "";
  for (const raw of inner.split(",")) {
    const part = raw.trim();
    let match: Citation | undefined;
    const full = /^([A-Za-z0-9][A-Za-z0-9._-]*)§(\S+)$/.exec(part);
    if (full) {
      match = citations.find((c) => c.paragraph_id === part);
    } else {
      const m = /^(.*?)\s*§(\S+)$/.exec(part);
      if (m) {
        const name = (m[1] ?? "").trim() || currentName;
        currentName = name;
        const ref = m[2] ?? "";
        const sameRef = citations.filter((c) => paragraphRef(c.paragraph_id) === ref);
        match = sameRef.find((c) => shortCaseName(c.case_name) === name) ?? sameRef[0];
      }
    }
    if (match && !found.includes(match)) found.push(match);
  }
  return found;
}

/** Turn bracketed markers in text that is not part of a claim into text + cite segments. */
function parseGap(gap: string, citations: Citation[]): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of gap.matchAll(BRACKET)) {
    const start = m.index ?? 0;
    const cites = resolveBracket(m[1] ?? "", citations);
    if (cites.length === 0) continue;
    if (start > last) out.push({ kind: "text", text: gap.slice(last, start) });
    out.push({ kind: "cite", citations: cites });
    last = start + m[0].length;
  }
  if (last < gap.length) out.push({ kind: "text", text: gap.slice(last) });
  return out;
}

const TRAILING_MARKERS_AT_END = /(?:\s*\[[^[\]]*§[^[\]]*\])*\s*$/;

/** Index of the next sentence-ending `.`/`!`/`?` (outside square brackets, followed by space or the end), or -1. */
function sentenceTerminator(text: string, from: number): number {
  let depth = 0;
  for (let i = from; i < text.length; i++) {
    const ch = text[i];
    if (ch === "[") depth++;
    else if (ch === "]") depth = Math.max(0, depth - 1);
    else if (depth === 0 && (ch === "." || ch === "!" || ch === "?") && (i + 1 >= text.length || /\s/.test(text[i + 1] ?? ""))) {
      return i;
    }
  }
  return -1;
}

const words = (s: string): string[] => s.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) ?? [];

/** The sentence at or after `from` that shares the most words with `claimText` (at least 60% of the claim's words). */
function bestSentenceStart(text: string, from: number, claimText: string): number {
  const wanted = new Set(words(claimText));
  if (wanted.size === 0) return -1;
  let best = -1;
  let bestScore = 0;
  let start = from;
  while (start < text.length) {
    while (start < text.length && /\s/.test(text[start] ?? "")) start++;
    if (start >= text.length) break;
    const t = sentenceTerminator(text, start);
    const end = t < 0 ? text.length : t;
    const have = new Set(words(text.slice(start, end).replace(/\[[^[\]]*§[^[\]]*\]/g, " ")));
    let hits = 0;
    for (const w of wanted) if (have.has(w)) hits++;
    const score = hits / wanted.size;
    if (score > bestScore) {
      bestScore = score;
      best = start;
    }
    if (t < 0) break;
    start = t + 1;
  }
  return bestScore >= 0.6 ? best : -1;
}

type Placement = { start: number; bodyEnd: number; cursorAfter: number; endsSentence: boolean };

/** Close the sentence that contains `start`: the claim text runs to its end, so chips never land mid-sentence. */
function placeInSentence(text: string, start: number, searchFrom: number): Placement {
  const t = sentenceTerminator(text, searchFrom);
  const sentenceEnd = t < 0 ? text.length : t;
  const raw = text.slice(start, sentenceEnd);
  const bodyEnd = start + raw.replace(TRAILING_MARKERS_AT_END, "").length;
  return { start, bodyEnd, cursorAfter: t < 0 ? text.length : t + 1, endsSentence: t >= 0 };
}

/**
 * Split `answer_text` into plain text, claims (with their citation chips) and bare citation markers.
 * The API writes each sentence as `<claim text> [Case §88, §91] [Other §3].`, so each claim is located
 * by its text and the markers after it are replaced by chips built from `claim.citation_ids`.
 * Chips always sit at the end of a sentence: when a claim's text is only part of a sentence, or is not in the
 * text verbatim, the claim is stretched to the end of the sentence that contains (or best matches) it.
 */
export function segmentAnswer(answer: Pick<Answer, "answer_text" | "claims" | "citations">): SegmentedAnswer {
  const text = answer.answer_text;
  const byId = new Map(answer.citations.map((c) => [c.paragraph_id, c]));
  const segments: Segment[] = [];
  const unplaced: AnswerClaim[] = [];
  let cursor = 0;
  for (const claim of answer.claims) {
    const body = claim.text.trim().replace(/\.$/, "");
    const at = body ? text.indexOf(body, cursor) : -1;
    let placed: Placement | null = null;
    if (at >= 0) {
      const end = at + body.length;
      TRAILING_MARKERS.lastIndex = end;
      const tail = TRAILING_MARKERS.exec(text);
      const afterTail = end + (tail ? tail[0].length : 0);
      const midSentence = tail?.[1] !== "." && /^\s*[a-z,;(]/.test(text.slice(afterTail));
      placed = midSentence
        ? placeInSentence(text, at, end)
        : { start: at, bodyEnd: end, cursorAfter: afterTail, endsSentence: tail?.[1] === "." };
    } else if (body) {
      const sentenceStart = bestSentenceStart(text, cursor, body);
      if (sentenceStart >= 0) placed = placeInSentence(text, sentenceStart, sentenceStart);
    }
    if (!placed) {
      unplaced.push(claim);
      continue;
    }
    if (placed.start > cursor) segments.push(...parseGap(text.slice(cursor, placed.start), answer.citations));
    const citations = claim.citation_ids.flatMap((id) => byId.get(id) ?? []);
    segments.push({
      kind: "claim",
      claim,
      text: text.slice(placed.start, placed.bodyEnd),
      citations,
      endsSentence: placed.endsSentence,
    });
    cursor = placed.cursorAfter;
  }
  if (cursor < text.length) segments.push(...parseGap(text.slice(cursor), answer.citations));
  return { segments, unplaced };
}

export type PointGroup = { heading: string | null; claims: AnswerClaim[] };

export type AnswerFirstLayout = {
  /** The one-sentence direct answer, unless it failed verification (then it is in `dropped`). */
  shortAnswer: AnswerClaim | null;
  /** The remaining points in reading order; consecutive points with the same `group` share a heading. */
  groups: PointGroup[];
  /** Claims that failed verification: shown apart, never as part of the answer. */
  dropped: AnswerClaim[];
};

/** True when the API sent a short answer or grouped points (older answers have neither field). */
export function isAnswerFirst(answer: Pick<Answer, "route" | "claims">): boolean {
  return answer.route === "rag" && answer.claims.some((c) => c.role === "short_answer" || c.group !== undefined);
}

/** Split claims into the short answer, points under their group headings, and the ones left out. */
export function answerFirstLayout(answer: Pick<Answer, "claims">): AnswerFirstLayout {
  let shortAnswer: AnswerClaim | null = null;
  const groups: PointGroup[] = [];
  const dropped: AnswerClaim[] = [];
  for (const claim of answer.claims) {
    if (claim.status === "unsupported") {
      dropped.push(claim);
    } else if (claim.role === "short_answer" && shortAnswer === null) {
      shortAnswer = claim;
    } else {
      const heading = claim.group ?? null;
      const last = groups[groups.length - 1];
      if (last && last.heading === heading) last.claims.push(claim);
      else groups.push({ heading, claims: [claim] });
    }
  }
  return { shortAnswer, groups, dropped };
}

export type StatusInfo = { label: string; symbol: string; meaning: string };

export function claimStatusInfo(status: AnswerClaim["status"]): StatusInfo {
  switch (status) {
    case "supported":
      return { label: "Supported", symbol: "✓", meaning: "A second check found the cited paragraph backs this claim." };
    case "unsupported":
      return {
        label: "Unsupported",
        symbol: "✕",
        meaning: "The check found that the cited paragraph does not back this claim, so it was left out of the answer.",
      };
    case "unverified":
      return { label: "Unverified", symbol: "?", meaning: "This claim has not been checked against its citation." };
  }
}

export function routeLabel(route: Answer["route"]): string {
  return route === "stats" ? "Stats: SQL over metadata" : "RAG: retrieved + cited";
}

export function formatCost(usd: number): string {
  if (usd === 0) return "$0.00";
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 1) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

export function formatLatency(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function formatTokens(n: number): string {
  return n.toLocaleString("en-US");
}

const STEP_LABELS: Record<AnswerStep["step"], string> = {
  route: "Route: choose RAG or SQL",
  retrieve: "Retrieve: find paragraphs",
  rerank: "Rerank: reorder them",
  generate: "Generate: write the claims",
  verify: "Verify: check each claim",
};

export function stepLabel(step: AnswerStep["step"]): string {
  return STEP_LABELS[step];
}

export function formatCell(cell: string | number | boolean | null): string {
  return cell === null ? "—" : String(cell);
}

/** Plain-words labels for the inadmissibility grounds (same wording as the stats answer sentence). */
const GROUND_LABELS: Record<string, string> = {
  manifestly_ill_founded: "manifestly ill-founded",
  non_exhaustion: "domestic remedies not exhausted",
  out_of_time: "out of time (six-month rule)",
  incompatible_ratione_materiae: "outside the Convention's subject matter",
  incompatible_ratione_personae: "outside the Convention as to persons",
  incompatible_ratione_temporis: "outside the Convention as to time",
  incompatible_ratione_loci: "outside the Convention as to territory",
  abuse_of_right: "abuse of the right of application",
  no_significant_disadvantage: "no significant disadvantage",
  substantially_same: "substantially the same as an earlier application",
  not_a_victim: "applicant not a victim",
  other: "another stated ground",
};

export function groundLabel(key: string): string {
  return GROUND_LABELS[key] ?? key.replace(/_/g, " ");
}

const COLUMN_LABELS: Record<string, string> = {
  documents: "Documents",
  reason: "Reason",
  article: "Article",
  outcome: "Outcome",
  doc_type: "Document type",
  year: "Year",
  set: "Counted",
};

export function statsColumnLabel(column: string): string {
  return COLUMN_LABELS[column] ?? column;
}

export type StatsCellDisplay = { label: string; key: string | null };

/**
 * A cell of the stats "rows" table: plain words for the enum keys the SQL groups by (`non_exhaustion` ->
 * "domestic remedies not exhausted"), with the raw `key` kept so the reader can match it to the SQL.
 */
export function statsCell(column: string, cell: string | number | boolean | null): StatsCellDisplay {
  const plain = { label: formatCell(cell), key: null };
  if (typeof cell !== "string") return plain;
  let label = cell;
  if (column === "reason" && cell !== "(not stated)") label = groundLabel(cell);
  else if (column === "outcome") label = outcomeLabel(cell as Parameters<typeof outcomeLabel>[0]);
  else if (column === "doc_type") label = docTypeLabel(cell as Parameters<typeof docTypeLabel>[0]);
  else if (column === "article") label = /^\d/.test(cell) ? `Article ${cell}` : cell.replace(/^P(\d+)-(\d+)$/, "Protocol $1, Article $2");
  return { label, key: label === cell ? null : cell };
}

const FOLLOW_UPS_MAX = 3;
const ARTICLE = /\bArticle\s+(\d+)\b/g;

/**
 * Two or three complete, standalone questions a reader of this answer might ask next, built from the cases and
 * Articles it cites. Each one is asked afresh (GET /ask?q=...): nothing about this answer is stored or sent along.
 */
export function followUpQuestions(answer: Pick<Answer, "question" | "route" | "answer_text" | "claims" | "citations" | "stats" | "refused_or_not_in_sources">): string[] {
  if (answer.refused_or_not_in_sources) return [];
  const cases: string[] = [];
  const addCase = (caseName: string, docType: Citation["doc_type"]) => {
    if (docType === "legislation") return;
    const name = shortCaseName(caseName);
    if (name && !cases.includes(name)) cases.push(name);
  };
  if (answer.route === "stats" && answer.stats) {
    for (const c of answer.stats.matching_cases) addCase(c.case_name, c.doc_type);
  } else {
    for (const c of answer.citations) addCase(c.case_name, c.doc_type);
  }
  const articles: string[] = [];
  const text = [answer.answer_text, ...answer.claims.map((c) => c.text)].join(" ");
  for (const m of text.matchAll(ARTICLE)) {
    const n = m[1] ?? "";
    if (n && !articles.includes(n)) articles.push(n);
  }
  const candidates = [
    cases[0] ? `What did the Court decide in ${cases[0]}, and why?` : null,
    articles[0] ? `How has the Court applied Article ${articles[0]} in UK cases?` : null,
    cases[1] ? `What did the Court decide in ${cases[1]}, and why?` : null,
    articles[1] ? `How has the Court applied Article ${articles[1]} in UK cases?` : null,
  ];
  const asked = answer.question.trim().toLowerCase();
  const out: string[] = [];
  for (const q of candidates) {
    if (q && q.toLowerCase() !== asked && !out.includes(q)) out.push(q);
    if (out.length === FOLLOW_UPS_MAX) break;
  }
  return out;
}

/**
 * A verbatim quote as shown in a source card: an ellipsis marks where it starts or stops inside a sentence (only
 * when a single sentence was longer than the quote budget), so a cut never reads as the whole sentence.
 */
export function displayQuote(quote: string): string {
  const q = quote.trim();
  if (!q) return q;
  const opensMidSentence = /^[a-z]/.test(q);
  const closesMidSentence = !/[.!?;:)\]"'”’]$/.test(q);
  return `${opensMidSentence ? "…" : ""}${q}${closesMidSentence ? "…" : ""}`;
}
