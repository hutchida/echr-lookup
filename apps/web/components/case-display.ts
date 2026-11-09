import type { CaseDetail } from "@echr/contract";

type Paragraph = CaseDetail["paragraphs"][number];
type Doc = CaseDetail["document"];

export type SectionGroup = { section: Paragraph["section"]; paragraphs: Paragraph[] };

/** Consecutive paragraphs under the same section heading, in document order. */
export function groupBySection(paragraphs: Paragraph[]): SectionGroup[] {
  const groups: SectionGroup[] = [];
  for (const p of paragraphs) {
    const last = groups[groups.length - 1];
    if (last && last.section === p.section) last.paragraphs.push(p);
    else groups.push({ section: p.section, paragraphs: [p] });
  }
  return groups;
}

/** `001-57619§88` -> `88`; `001-57619§op1` -> `op1`. */
export function paragraphRef(id: string): string {
  return id.split("§")[1] ?? id;
}

/** The DOM id for a paragraph: `p<ref>`. */
export function paragraphDomId(id: string): string {
  return `p${paragraphRef(id)}`;
}

/** The number shown in the margin: the printed number, or a readable form of the ref (`op1` -> `Op. 1`). */
export function paragraphLabel(p: Pick<Paragraph, "id" | "number">): string {
  if (p.number !== null) return String(p.number);
  const ref = paragraphRef(p.id);
  const op = /^op(\d+)$/.exec(ref);
  if (op) return `Op. ${op[1]}`;
  const art = /^art(\d+)$/.exec(ref);
  if (art) return `Art. ${art[1]}`;
  const s = /^s(\d+)$/.exec(ref);
  if (s) return `s. ${s[1]}`;
  return ref;
}

function humanise(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export const outcomeLabel = (outcome: Doc["outcome"]): string =>
  outcome === "not_applicable"
    ? "Not applicable"
    : outcome === "mixed"
      ? "Mixed (violation and no-violation findings)"
      : humanise(outcome);

export const docTypeLabel = (docType: Doc["doc_type"]): string => humanise(docType);

const IMPORTANCE: Record<number, string> = { 1: "1 (key case)", 2: "2 (high)", 3: "3 (medium)", 4: "4 (low)" };

export function importanceLabel(importance: number | null): string {
  return importance === null ? "—" : (IMPORTANCE[importance] ?? String(importance));
}

/** HUDOC article codes for display: `8-1` -> `Art. 8-1`; `P1-3` stays as is. */
export function articlesLabel(articles: string[]): string {
  return articles.length === 0 ? "—" : articles.map((a) => (/^\d/.test(a) ? `Art. ${a}` : a)).join(", ");
}

/** `001-98645`'s title for display: `MIAH v. THE UNITED KINGDOM` -> `Miah v. The United Kingdom`. */
export function caseTitle(name: string): string {
  const letters = [...name].filter((c) => /\p{L}/u.test(c));
  const upper = letters.filter((c) => c === c.toUpperCase() && c !== c.toLowerCase()).length;
  if (letters.length === 0 || upper / letters.length <= 0.6) return name;
  return name
    .split(/\s+/)
    .map((w) =>
      /^(?:[A-Z]\.)+[A-Z]?\.?$/.test(w) || w === "v."
        ? w
        : w
            .split("-")
            .map((p) => p.charAt(0) + p.slice(1).toLowerCase())
            .join("-"),
    )
    .join(" ");
}
