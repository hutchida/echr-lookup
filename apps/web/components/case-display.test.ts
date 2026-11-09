import { describe, expect, it } from "vitest";
import caseFixture from "@echr/contract/fixtures/CaseDetail.json";
import { CaseDetail } from "@echr/contract";
import {
  articlesLabel,
  caseTitle,
  docTypeLabel,
  groupBySection,
  importanceLabel,
  outcomeLabel,
  paragraphDomId,
  paragraphLabel,
} from "./case-display";

const kase = CaseDetail.parse(caseFixture);

describe("groupBySection", () => {
  it("keeps document order and every paragraph", () => {
    const groups = groupBySection(kase.paragraphs);
    expect(groups.flatMap((g) => g.paragraphs.map((p) => p.id))).toEqual(kase.paragraphs.map((p) => p.id));
    expect(groups.map((g) => g.section)).toEqual(["The Facts", "The Law"]);
  });

  it("starts a new group when a section repeats later", () => {
    const [a, b] = kase.paragraphs as [(typeof kase.paragraphs)[number], (typeof kase.paragraphs)[number]];
    const groups = groupBySection([a, { ...b, section: "The Law" }, { ...b, section: "The Facts" }]);
    expect(groups.map((g) => g.section)).toEqual(["The Facts", "The Law", "The Facts"]);
  });

  it("returns nothing for no paragraphs", () => {
    expect(groupBySection([])).toEqual([]);
  });
});

describe("paragraph display", () => {
  it("builds the anchor id the citations link to", () => {
    expect(paragraphDomId(kase.paragraphs[0]!.id)).toBe("p1");
  });

  it("shows the printed number, or a readable ref for unnumbered items", () => {
    expect(paragraphLabel({ id: "001-98645§12", number: 12 })).toBe("12");
    expect(paragraphLabel({ id: "001-98645§op1", number: null })).toBe("Op. 1");
    expect(paragraphLabel({ id: "echr-convention§art8", number: null })).toBe("Art. 8");
    expect(paragraphLabel({ id: "ukpga-1998-42§s3", number: null })).toBe("s. 3");
    expect(paragraphLabel({ id: "001-98645§u3", number: null })).toBe("u3");
  });
});

describe("header labels", () => {
  it("humanises metadata", () => {
    const d = kase.document;
    expect(outcomeLabel(d.outcome)).toBe("Inadmissible");
    expect(outcomeLabel("no_violation")).toBe("No violation");
    expect(outcomeLabel("not_applicable")).toBe("Not applicable");
    expect(outcomeLabel("mixed")).toBe("Mixed (violation and no-violation findings)");
    expect(docTypeLabel(d.doc_type)).toBe("Decision");
    expect(importanceLabel(d.importance)).toBe("4 (low)");
    expect(importanceLabel(null)).toBe("—");
    expect(articlesLabel(d.articles)).toBe("Art. 3, Art. 7, Art. 8");
    expect(articlesLabel(["P1-3", "8-1"])).toBe("P1-3, Art. 8-1");
    expect(articlesLabel([])).toBe("—");
    expect(caseTitle(d.case_name)).toBe("Miah v. The United Kingdom");
    expect(caseTitle("Soering v. The United Kingdom")).toBe("Soering v. The United Kingdom");
  });
});
