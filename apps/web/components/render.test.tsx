import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { Answer } from "@echr/contract";
import answerFixture from "@echr/contract/fixtures/Answer.json";
import answerFirstFixture from "@echr/contract/fixtures/Answer.answer-first.json";
import statsFixture from "@echr/contract/fixtures/Answer.stats.json";
import refusedFixture from "@echr/contract/fixtures/Answer.refused.json";
import { AnswerView } from "./answer-view";
import { ErrorNotice } from "./error-notice";

const count = (html: string, needle: string) => html.split(needle).length - 1;

describe("AnswerView", () => {
  it("renders a RAG answer with chips, badges, route and cost", () => {
    const html = renderToString(<AnswerView answer={Answer.parse(answerFixture)} />);
    expect(html).toContain('data-testid="answer-route"');
    expect(html).toContain("RAG: retrieved + cited");
    expect(count(html, 'data-testid="citation"')).toBe(2); // one per claim, at the end of the sentence it best matches
    expect(html).toContain('href="/case/001-57619#p91"');
    expect(html).toContain('data-testid="claim-status"');
    expect(html).toContain("Unverified");
    expect(html).toContain('data-testid="answer-cost"');
    expect(html).toContain("Generate: write the claims");
  });

  it("renders the short answer first and prominently, then the points under their group headings", () => {
    const html = renderToString(<AnswerView answer={Answer.parse(answerFirstFixture)} />);
    expect(html).toContain('data-testid="short-answer"');
    expect(html).toContain("Short answer");
    expect(html.indexOf('data-testid="short-answer"')).toBeLessThan(html.indexOf('data-testid="claim-group"'));
    expect(count(html, 'data-testid="claim-group"')).toBe(2);
    expect(html).toContain("The test");
    expect(html).toContain("How the Court applied it");
    expect(count(html, 'data-testid="claim"')).toBe(2); // the points; the short answer has its own testid
    expect(count(html, 'data-testid="claim-status"')).toBe(3); // badge on the short answer and on every point
    expect(count(html, 'data-testid="citation"')).toBe(4); // chips: 2 on the short answer, 1 on each point
    expect(html).toContain('href="/case/001-57619#p111"');
  });

  it("renders an old answer (no role or group) exactly as before: no short-answer card", () => {
    const html = renderToString(<AnswerView answer={Answer.parse(answerFixture)} />);
    expect(html).not.toContain('data-testid="short-answer"');
    expect(html).not.toContain('data-testid="claim-group"');
  });

  it("renders a stats answer with its SQL, count and matching cases", () => {
    const answer = Answer.parse(statsFixture);
    const html = renderToString(<AnswerView answer={answer} />);
    expect(html).toContain("Stats: SQL over metadata");
    expect(html).toContain('data-testid="stats-sql"');
    expect(html).toContain("SELECT");
    expect(count(html, 'data-testid="matching-case"')).toBe(answer.stats!.matching_cases.length);
    expect(html).toContain('href="/case/001-231646"');
    expect(html).toContain('data-testid="answer-cost"');
  });

  it("renders a refusal calmly, with no chips", () => {
    const html = renderToString(<AnswerView answer={Answer.parse(refusedFixture)} />);
    expect(html).toContain('data-testid="answer-refused"');
    expect(html).toContain("No answer from the sources");
    expect(html).not.toContain('data-testid="citation"');
    expect(html).toContain('data-testid="answer-cost"');
  });
});

describe("ErrorNotice", () => {
  it("is an alert with the message", () => {
    const html = renderToString(<ErrorNotice title="Can’t reach the API" message="fetch failed" />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("fetch failed");
  });
});
