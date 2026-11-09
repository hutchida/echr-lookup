import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { Answer, CorpusStats } from "@echr/contract";
import corpusFixture from "@echr/contract/fixtures/CorpusStats.json";
import answerFixture from "@echr/contract/fixtures/Answer.json";
import answerFirstFixture from "@echr/contract/fixtures/Answer.answer-first.json";
import statsFixture from "@echr/contract/fixtures/Answer.stats.json";
import refusedFixture from "@echr/contract/fixtures/Answer.refused.json";
import { CorpusScope, corpusScope } from "./corpus-scope";
import { CitationChip } from "./citation-chip";
import { FollowUps } from "./follow-ups";
import { displayQuote, followUpQuestions } from "./answer-display";

const corpus = CorpusStats.parse(corpusFixture);
const rag = Answer.parse(answerFirstFixture);

describe("Ask corpus line", () => {
  it("states the live document count, UK-only scope and that the snapshot is a small sample", () => {
    const t = corpusScope(corpus);
    expect(t.size).toBe(`${corpus.totals.documents} documents`); // from GET /stats, never hardcoded
    expect(t.scope).toContain("United Kingdom cases");
    expect(t.scope).toContain("judgments, decisions and legal summaries");
    expect(t.sample).toContain("small committed sample, not the full HUDOC download");
    const html = renderToString(<CorpusScope stats={corpus} />);
    expect(html).toContain('data-testid="corpus-scope"');
    expect(html).toContain(`${corpus.totals.documents} documents`);
    expect(html).toContain('href="/stats"');
  });

  it("counts legislation separately from cases and drops the sample warning for the full corpus", () => {
    const full = {
      ...corpus,
      data_source: "full" as const,
      totals: { ...corpus.totals, documents: 3527 },
      by_doc_type: [...corpus.by_doc_type, { key: "legislation", count: 2 }],
    };
    const t = corpusScope(full);
    expect(t.size).toBe("3,527 documents");
    expect(t.scope).toContain("plus 2 legislation texts");
    expect(t.sample).toBeNull();
  });

  it("omits the numbers when the stats call failed, rather than inventing them", () => {
    const t = corpusScope(null);
    expect(t.size).toBeNull();
    expect(t.sample).toBeNull();
    const html = renderToString(<CorpusScope stats={null} />);
    expect(html).toContain("United Kingdom cases");
    expect(html).not.toMatch(/\d+ documents/);
    expect(html).not.toContain('data-testid="corpus-size"');
    expect(html).toContain('href="/stats"');
  });
});

describe("citation chip", () => {
  it("shows the document type, and sets a legal summary apart from the judgment", () => {
    const judgment = rag.citations[0]!;
    const summary = { ...judgment, paragraph_id: "002-428§u3", doc_id: "002-428", doc_type: "legal_summary" as const, link_target: "/case/002-428#pu3" };
    const jHtml = renderToString(<CitationChip citation={judgment} />);
    const sHtml = renderToString(<CitationChip citation={summary} />);
    expect(jHtml).toContain(">Judgment<");
    expect(sHtml).toContain(">Legal summary<");
    expect(sHtml).toContain('data-doc-type="legal_summary"');
    expect(sHtml).toContain('aria-label="Soering v UK §u3 · Legal summary"');
    expect(sHtml).toContain('href="/case/002-428#pu3"');
  });
});

describe("follow-up questions", () => {
  it("are complete standalone questions from the cited cases and Articles", () => {
    const qs = followUpQuestions(rag);
    expect(qs.length).toBeGreaterThanOrEqual(2);
    expect(qs.length).toBeLessThanOrEqual(3);
    expect(qs).toContain("What did the Court decide in Soering v UK, and why?");
    expect(qs).toContain("How has the Court applied Article 3 in UK cases?");
    for (const q of qs) {
      expect(q).toMatch(/\?$/);
      expect(q).not.toMatch(/\b(it|this case|that case|these|above)\b/i); // no reference back to the answer
    }
  });

  it("use the stats route's matching cases, and none follow a refused answer", () => {
    const stats = followUpQuestions(Answer.parse(statsFixture));
    expect(stats[0]).toMatch(/^What did the Court decide in Horne v UK/);
    expect(followUpQuestions(Answer.parse(refusedFixture))).toEqual([]);
  });

  it("render as plain GET links to a new /ask question, with no previous-question state", () => {
    const html = renderToString(<FollowUps answer={Answer.parse(answerFixture)} />);
    const links = html.split('data-testid="follow-up"').length - 1;
    expect(links).toBeGreaterThanOrEqual(2);
    for (const q of followUpQuestions(Answer.parse(answerFixture))) {
      expect(html).toContain(`href="/ask?q=${encodeURIComponent(q).replace(/'/g, "&#x27;")}"`);
    }
    expect(html).toContain('action="/ask"');
    expect(html).toContain('method="get"');
    expect(html).not.toContain('type="hidden"'); // nothing about this answer travels with the next question
    expect(html).toContain('data-testid="ask-follow-up-input"');
  });
});

describe("source quotes", () => {
  it("mark a cut inside an over-long sentence with an ellipsis, and leave whole sentences alone", () => {
    expect(displayQuote("Holds that there has been a violation of Article 3;")).toBe("Holds that there has been a violation of Article 3;");
    expect(displayQuote("The Court so held.")).toBe("The Court so held.");
    expect(displayQuote("the exercise of public powers abroad")).toBe("…the exercise of public powers abroad…");
    expect(displayQuote("A further legal basis might be provided by the agreement, that the")).toBe(
      "A further legal basis might be provided by the agreement, that the…",
    );
  });
});
