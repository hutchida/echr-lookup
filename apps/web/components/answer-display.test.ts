import { describe, expect, it } from "vitest";
import answerFixture from "@echr/contract/fixtures/Answer.json";
import answerFirstFixture from "@echr/contract/fixtures/Answer.answer-first.json";
import statsFixture from "@echr/contract/fixtures/Answer.stats.json";
import refusedFixture from "@echr/contract/fixtures/Answer.refused.json";
import { Answer } from "@echr/contract";
import {
  answerFirstLayout,
  chipRef,
  docTypeShortLabel,
  chipLabel,
  claimStatusInfo,
  formatCell,
  formatCost,
  formatLatency,
  paragraphDomId,
  paragraphRef,
  routeLabel,
  groundLabel,
  isAnswerFirst,
  segmentAnswer,
  shortCaseName,
  statsCell,
  statsColumnLabel,
  stepLabel,
} from "./answer-display";

const rag = Answer.parse(answerFixture);
const answerFirst = Answer.parse(answerFirstFixture);
const stats = Answer.parse(statsFixture);
const refused = Answer.parse(refusedFixture);

/** An answer in the exact shape the API writes: `<claim> [Case §88, §91] [Other §3].` */
const apiShaped = Answer.parse({
  ...answerFixture,
  answer_text:
    "Intro line. Extradition can engage the sending state's responsibility [Soering v UK §91]. The Court found a breach [Soering v UK §111] [Chahal v UK §74, §91]. Uncited claim.",
  claims: [
    { ...answerFixture.claims[0], text: "Extradition can engage the sending state's responsibility" },
    {
      ...answerFixture.claims[1],
      text: "The Court found a breach.",
      citation_ids: ["001-57619§111", "001-22225§74"],
    },
    { ...answerFixture.claims[1], id: "c3", text: "Uncited claim", citation_ids: [], status: "supported" },
    { ...answerFixture.claims[1], id: "c4", text: "Dropped claim", citation_ids: ["001-57619§91"], status: "unsupported" },
  ],
  citations: [
    ...answerFixture.citations,
    { ...answerFixture.citations[0], paragraph_id: "001-22225§74", doc_id: "001-22225", case_name: "CHAHAL v. THE UNITED KINGDOM", link_target: "/case/001-22225#p74" },
  ],
});

describe("paragraph refs", () => {
  it("splits the id after the section sign", () => {
    expect(paragraphRef("001-57619§88")).toBe("88");
    expect(paragraphRef("001-57619§op3")).toBe("op3");
    expect(paragraphDomId("001-57619§88")).toBe("p88");
    expect(paragraphDomId("ukpga-1998-42§s3")).toBe("ps3");
  });

  it("every fixture citation link_target matches the case page anchor", () => {
    for (const a of [rag, stats, refused]) {
      for (const c of a.citations) {
        expect(c.link_target).toBe(`/case/${c.doc_id}#${paragraphDomId(c.paragraph_id)}`);
      }
    }
  });
});

describe("shortCaseName / chipLabel", () => {
  it("shortens like the API's inline markers", () => {
    expect(shortCaseName("SOERING v. THE UNITED KINGDOM")).toBe("Soering v UK");
    expect(shortCaseName("Soering v. The United Kingdom")).toBe("Soering v UK");
    expect(shortCaseName("CASE OF A.H. v. THE UNITED KINGDOM (dec.)")).toBe("A.H. v UK");
    expect(shortCaseName("X".repeat(60))).toHaveLength(40);
  });

  it("labels a chip with case, paragraph and document type", () => {
    expect(chipRef(rag.citations[0]!)).toBe("Soering v UK §91");
    expect(chipLabel(rag.citations[0]!)).toBe("Soering v UK §91 · Judgment");
  });

  it("tells a legal summary apart from the judgment it summarises", () => {
    const judgment = { ...rag.citations[0]!, case_name: "AL-SKEINI AND OTHERS v. THE UNITED KINGDOM", paragraph_id: "001-105606§150", doc_id: "001-105606" };
    const summary = { ...judgment, paragraph_id: "002-428§u3", doc_id: "002-428", doc_type: "legal_summary" as const };
    expect(chipLabel(judgment)).toBe("Al-Skeini and Others v UK §150 · Judgment");
    expect(chipLabel(summary)).toBe("Al-Skeini and Others v UK §u3 · Legal summary");
    expect(docTypeShortLabel("decision")).toBe("Decision");
    expect(docTypeShortLabel("legislation")).toBe("Legislation");
  });
});

describe("segmentAnswer", () => {
  it("places each claim, chips from citation_ids, and keeps surrounding text", () => {
    const { segments, unplaced } = segmentAnswer(apiShaped);
    expect(segments[0]).toEqual({ kind: "text", text: "Intro line. " });
    const claims = segments.filter((s) => s.kind === "claim");
    expect(claims.map((c) => c.text)).toEqual([
      "Extradition can engage the sending state's responsibility",
      "The Court found a breach",
      "Uncited claim",
    ]);
    expect(claims[0]!.citations.map((c) => c.paragraph_id)).toEqual(["001-57619§91"]);
    expect(claims[1]!.citations.map((c) => c.paragraph_id)).toEqual(["001-57619§111", "001-22225§74"]);
    expect(claims.every((c) => c.endsSentence)).toBe(true);
    expect(claims[2]!.citations).toEqual([]);
    expect(unplaced.map((c) => c.id)).toEqual(["c4"]);
  });

  it("never loses text: claim bodies and gaps rebuild the visible words", () => {
    const { segments } = segmentAnswer(apiShaped);
    const words = segments
      .map((s) => (s.kind === "text" ? s.text : s.kind === "claim" ? s.text : ""))
      .join("")
      .replace(/\s+/g, " ");
    expect(words).toContain("Intro line.");
    expect(words).not.toContain("[");
  });

  it("places a claim whose text is not in the answer at the end of the sentence that best matches it", () => {
    const { segments, unplaced } = segmentAnswer(rag);
    expect(unplaced).toEqual([]);
    const claims = segments.filter((s) => s.kind === "claim");
    expect(claims.map((c) => c.claim.id)).toEqual(["c1", "c2"]);
    expect(claims[0]!.citations.map((x) => x.paragraph_id)).toEqual(["001-57619§91"]);
    expect(claims[1]!.citations.map((x) => x.paragraph_id)).toEqual(["001-57619§111"]);
    expect(claims.every((c) => c.endsSentence)).toBe(true);
    expect(claims[1]!.text.endsWith("would breach Article 3")).toBe(true);
    expect(segments.some((s) => s.kind === "text" && s.text.includes("[001"))).toBe(false);
  });

  it("falls back to bracket parsing when no sentence resembles the claim", () => {
    const { segments, unplaced } = segmentAnswer({
      ...rag,
      claims: rag.claims.map((c) => ({ ...c, text: "Something else entirely about fishing quotas." })),
    });
    expect(unplaced).toHaveLength(2);
    const cites = segments.filter((s) => s.kind === "cite");
    expect(cites.map((c) => c.citations.map((x) => x.paragraph_id))).toEqual([["001-57619§91"], ["001-57619§111"]]);
  });

  it("never puts chips mid-sentence: a claim that is only the start of a sentence is stretched to its end", () => {
    const answer = Answer.parse({
      ...answerFixture,
      answer_text:
        "27 judgments about removal with outcome inadmissible are in the indexed corpus. Most common reasons: a (2); b (1). Examples: [Soering v UK §91]",
      claims: [
        { ...answerFixture.claims[0], id: "c1", text: "27 judgments about removal with outcome inadmissible.", citation_ids: ["001-57619§91"] },
        { ...answerFixture.claims[0], id: "c2", text: "Most common reasons: a (2); b (1).", citation_ids: ["001-57619§91"] },
      ],
    });
    const { segments, unplaced } = segmentAnswer(answer);
    expect(unplaced).toEqual([]);
    const claims = segments.filter((s) => s.kind === "claim");
    expect(claims[0]!.text).toBe("27 judgments about removal with outcome inadmissible are in the indexed corpus");
    expect(claims[0]!.endsSentence).toBe(true);
    expect(claims[1]!.text).toBe("Most common reasons: a (2); b (1)");
  });

  it("places a differently worded stats claim at the end of its sentence", () => {
    const answer = Answer.parse({
      ...answerFixture,
      answer_text:
        "The indexed corpus has 27 UK judgments and decisions about deportation that were declared inadmissible. Most common reasons: x (22).",
      claims: [
        {
          ...answerFixture.claims[0],
          id: "c1",
          text: "27 judgments and decisions about deportation with outcome inadmissible.",
          citation_ids: ["001-57619§91"],
        },
      ],
    });
    const { segments, unplaced } = segmentAnswer(answer);
    expect(unplaced).toEqual([]);
    expect(segments.map((s) => s.kind)).toEqual(["claim", "text"]);
    const claim = segments[0]!;
    expect(claim.kind === "claim" && claim.text).toBe(
      "The indexed corpus has 27 UK judgments and decisions about deportation that were declared inadmissible",
    );
    expect(claim.kind === "claim" && claim.endsSentence).toBe(true);
  });

  it("leaves a marker it cannot resolve as plain text", () => {
    const { segments } = segmentAnswer({ answer_text: "See [Nobody v UK §9].", claims: [], citations: [] });
    expect(segments).toEqual([{ kind: "text", text: "See [Nobody v UK §9]." }]);
  });

  it("stats and refused answers become one text segment, with the stats claims unplaced", () => {
    const s = segmentAnswer(stats);
    expect(s.segments).toEqual([{ kind: "text", text: stats.answer_text }]);
    expect(s.unplaced).toHaveLength(stats.claims.length);
    const r = segmentAnswer(refused);
    expect(r.segments).toEqual([{ kind: "text", text: refused.answer_text }]);
    expect(r.unplaced).toEqual([]);
  });
});

describe("labels and formatting", () => {
  it("describes each verification status without relying on colour", () => {
    expect(claimStatusInfo("supported").label).toBe("Supported");
    expect(claimStatusInfo("unsupported").symbol).toBe("✕");
    expect(new Set(["supported", "unsupported", "unverified"].map((s) => claimStatusInfo(s as "supported").symbol)).size).toBe(3);
  });

  it("names the route", () => {
    expect(routeLabel(rag.route)).toBe("RAG: retrieved + cited");
    expect(routeLabel(stats.route)).toBe("Stats: SQL over metadata");
  });

  it("formats cost, latency and cells", () => {
    expect(formatCost(0)).toBe("$0.00");
    expect(formatCost(0.00566)).toBe("$0.0057");
    expect(formatCost(0.00000047)).toBe("<$0.0001");
    expect(formatCost(1.234)).toBe("$1.23");
    expect(formatLatency(310)).toBe("310 ms");
    expect(formatLatency(3822.2)).toBe("3.8 s");
    expect(formatCell(null)).toBe("—");
    expect(formatCell(19)).toBe("19");
  });

  it("labels every step in the fixture", () => {
    for (const step of rag.steps) expect(stepLabel(step.step)).toMatch(/:/);
    expect(rag.steps.reduce((t, s) => t + s.cost_usd, 0)).toBeCloseTo(rag.total_cost_usd, 5);
  });
});

describe("stats table labels", () => {
  it("shows plain words for enum keys and keeps the key for matching the SQL", () => {
    expect(statsCell("reason", "manifestly_ill_founded")).toEqual({ label: "manifestly ill-founded", key: "manifestly_ill_founded" });
    expect(statsCell("reason", "non_exhaustion").label).toBe("domestic remedies not exhausted");
    expect(statsCell("reason", "incompatible_ratione_materiae").label).toBe("outside the Convention's subject matter");
    expect(statsCell("reason", "(not stated)")).toEqual({ label: "(not stated)", key: null });
    expect(statsCell("outcome", "partly_inadmissible").label).toBe("Partly inadmissible");
    expect(statsCell("doc_type", "legal_summary").label).toBe("Legal summary");
    expect(statsCell("article", "3")).toEqual({ label: "Article 3", key: "3" });
    expect(statsCell("article", "Article 3")).toEqual({ label: "Article 3", key: null });
  });

  it("leaves numbers, years and nulls alone and never shows an underscore label", () => {
    expect(statsCell("documents", 27)).toEqual({ label: "27", key: null });
    expect(statsCell("year", 2019)).toEqual({ label: "2019", key: null });
    expect(statsCell("reason", null)).toEqual({ label: "—", key: null });
    expect(groundLabel("something_new")).toBe("something new");
    expect(statsColumnLabel("doc_type")).toBe("Document type");
    expect(statsColumnLabel("documents")).toBe("Documents");
  });
});

describe("answer-first layout", () => {
  it("is used only when the API sent a short answer or groups (old answers render as before)", () => {
    expect(isAnswerFirst(answerFirst)).toBe(true);
    expect(isAnswerFirst(rag)).toBe(false);
    expect(isAnswerFirst(stats)).toBe(false);
  });

  it("puts the short answer first and groups consecutive points under their heading", () => {
    const layout = answerFirstLayout(answerFirst);
    expect(layout.shortAnswer?.role).toBe("short_answer");
    expect(layout.groups.map((g) => g.heading)).toEqual(["The test", "How the Court applied it"]);
    expect(layout.groups.map((g) => g.claims.length)).toEqual([1, 1]);
    expect(layout.dropped).toEqual([]);
  });

  it("merges adjacent points with the same group and keeps ungrouped points together", () => {
    const base = answerFirst.claims[1]!;
    const claims = [
      { ...answerFirst.claims[0]! },
      { ...base, id: "c2", group: "A" },
      { ...base, id: "c3", group: "A" },
      { ...base, id: "c4", group: undefined },
      { ...base, id: "c5", group: undefined },
      { ...base, id: "c6", group: "A" },
    ];
    const layout = answerFirstLayout({ claims });
    expect(layout.groups.map((g) => [g.heading, g.claims.map((c) => c.id)])).toEqual([
      ["A", ["c2", "c3"]],
      [null, ["c4", "c5"]],
      ["A", ["c6"]],
    ]);
  });

  it("sets an unsupported short answer or point aside instead of showing it as part of the answer", () => {
    const claims = answerFirst.claims.map((c, i) => (i < 2 ? { ...c, status: "unsupported" as const } : c));
    const layout = answerFirstLayout({ claims });
    expect(layout.shortAnswer).toBeNull();
    expect(layout.dropped.map((c) => c.id)).toEqual(["c1", "c2"]);
    expect(layout.groups.map((g) => g.heading)).toEqual(["How the Court applied it"]);
  });
});
