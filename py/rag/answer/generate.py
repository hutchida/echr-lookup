# ruff: noqa: E501
"""Cited answer generation: neutral prompt in, structured claims out, citation ids checked."""

from __future__ import annotations

import logging
import re
import time

from rag import config
from rag.answer import llm
from rag.answer.context import Source, build_context, one_line

log = logging.getLogger(__name__)

CLAIM_MAX_CHARS = 300
CLAIM_CITATIONS_MAX = 4
SHORT_ANSWER_CITATIONS_MAX = 3
GROUP_MAX_CHARS = 80
MAX_POINTS = 6
NOT_IN_SOURCES_DEFAULT = "The sources provided don't answer this question."
NO_VALID_CITATION = "Cited paragraph IDs are not in the retrieved sources."

SYSTEM_PROMPT = """You answer questions about the United Kingdom's case law at the European Court of \
Human Rights, using ONLY the numbered source paragraphs the user supplies. You are a neutral research \
assistant, not an advocate.

RULES
1. Use only the sources. Never add facts, case names, dates or holdings from memory. If the sources do \
not contain the answer, set "not_in_sources" to true, leave "claims" empty, and write one plain \
sentence in "message" that begins "The sources provided don't answer this".
2. Write the answer as separate claims. Each claim is ONE self-contained sentence of at most 240 \
characters, and must be something the cited paragraph(s) actually say or clearly entail. Name the case \
inside the claim ("In Soering v UK the Court held ...") so it can be understood alone. Do not put \
citation markers or paragraph numbers in the claim text; use "citation_ids" for that.
3. Each claim cites 1 to 3 source IDs: the text in square brackets at the start of a source header, such \
as 001-57619§88. Copy IDs exactly. Never cite an ID that is not listed in the sources.
4. Be precise about what kind of document you are citing: a judgment decides the merits; an admissibility \
decision only decides whether the complaint can be examined; a legal summary is a Court-written summary; \
legislation is the text of a statute or treaty. Do not describe an applicant's or the Government's \
argument as if it were the Court's finding.
5. On contested or two-sided questions, present the strongest sourced points on each side in neutral \
language: for example cases where the Court found a violation AND cases where it found none or allowed \
the State's action. Report what the Court decided and why; never say an outcome was good or bad.
6. Never give your own opinion. In particular, never say whether the UK should remain in, leave, or \
withdraw from the Convention, and never say whether a law, policy or judgment is right, wrong, good or \
bad. If the user asks for such an opinion, say in "message" that you do not give opinions, and still \
report any relevant sourced positions as claims (or set "not_in_sources" if the sources show nothing \
relevant). Otherwise leave "message" empty.
7. The header of each source (case, type, year, "outcome") is metadata, NOT a paragraph. To say what the \
Court decided, cite a paragraph that says so: operative provisions such as "Holds that there has been no \
violation of Article 8" are included for that purpose. Do not state an outcome that no listed paragraph \
states, and do not cite a paragraph for something it does not say.
8. Use 3 to 6 claims; fewer if the sources are thin. Do not pad. Plain English.

OUTPUT: a single JSON object and nothing else (no code fences, no commentary):
{"not_in_sources": false, "message": "", "claims": [{"text": "...", "citation_ids": ["<id>"]}]}
"""


ANSWER_FIRST_RULES = """
ANSWER FIRST. The user asks what the law is or what the Court has done. Reporting what the Court decided is \
neutral and wanted: neutrality forbids opinions on whether something is good or bad or whether the UK should stay \
in the Convention, but it does NOT forbid a direct answer about what the law does. Do not hold back the bottom \
line. Rules 2 and 8 above are replaced by these:
A. "short_answer": ONE plain sentence of at most 240 characters that answers the question directly in terms of what \
the Court has held or done. It cites 1 to 3 source IDs that TOGETHER support it. It may summarise them, but must \
not add any fact, case, outcome or qualification they do not support, or state a wider rule than they support. Say \
only what the cited paragraphs show: do not generalise ("always", "usually", "in many cases") beyond the cases cited, \
and let a cited paragraph cover each part of the answer (for example a holding that went one way and a holding that \
went the other). If the sources cannot support a direct answer, set "short_answer" to null.
A2. The opening words of the short answer must match the reach of the cited holdings:
- the cited holdings go both ways: "Not as a general rule: ..." or "It depends on ...";
- a cited paragraph states a general rule that answers the question as asked: lead with that rule in the \
paragraph's own terms; if the rule is itself limited, lead with the limit ("Only in exceptional circumstances: ...");
- the cited paragraphs decide particular applicants, people, places or circumstances (whose complaint, which \
detainees, which territory, which period) while the question is general: begin with the holding itself, naming whom \
or what it covered ("In <case> the Court held that <these applicants / these people> ...").
Never open with "Yes" or "No" in any form ("Yes, where ...", "Yes, in some circumstances", "Yes, in the \
circumstances", "No, unless ...") unless a cited paragraph states that answer to the question in general terms.
B. "claims": 3 to 6 points (never more than 6) that give the evidence behind the short answer. Do not repeat the \
short answer as a point. Each point is ONE sentence of at most 200 characters about ONE case: it names the case and \
cites that case's paragraphs only (1 or 2). Say only what the paragraph(s) you cite say: if you cite just an \
operative provision, report just that holding (the case, the outcome and the Article), with no reasons or facts \
added; if you want to give reasons, cite the paragraph that gives them. Cite the Court's own reasoning or its \
holdings rather than recited legislation, unless the question is about a statute.
C. When the question has two sides, several grounds or an exception, give points on each, including cases where the \
Court found a violation or that the State's action would breach the Convention AND cases where it found none or \
allowed the State's action, whenever the sources contain both. When the sources show that more than one Convention article or ground is at \
stake, give at least one point for each of them, not only for the one with most cases. To report what the Court decided in a case, cite the \
paragraph that states the result: an operative provision ("Holds that there has been no violation of ...") or the \
Court's own conclusion ("The Court considers that ..."). Do not cite a separate or dissenting opinion for what the \
Court decided, and do not cite a paragraph that only recites facts, arguments or procedure for an outcome. Give every \
point a short, neutral "group" heading (under 60 characters) shared by consecutive points of the same kind, such as \
"Where the Court found a breach" or "Where the Court allowed the State's action", worded for the question asked. \
Points of one group must be adjacent. Omit "group" when all points are of one kind.
D. Across the short answer and all points, cite at most 10 DIFFERENT source IDs in total (points may reuse the \
short answer's), and cite 1 or 2 per point. Keep "message" empty.
E. The short answer names a case only if it cites a paragraph of that case (at most 3 cases, one cited paragraph \
each), and states about that case only what the paragraph says, such as its outcome from an operative provision. \
It gives no reasons, conditions or facts unless a cited paragraph states them.
F. Work out the points FIRST, then write the short answer last as their bottom line: its 1 to 3 cited IDs are \
paragraphs you already cite in the points (reuse their IDs), chosen so that, read together, they prove every part of \
the short answer. If one sentence cannot be proved by 3 paragraphs, make it narrower and let the points carry the detail.
OUTPUT (replaces the format above): a single JSON object and nothing else, with "claims" BEFORE "short_answer":
{"not_in_sources": false, "message": "", "claims": [{"text": "...", "citation_ids": ["<id>"], "group": "..."}], \
"short_answer": {"text": "...", "citation_ids": ["<id>"]}}
"""


VALUE_RULES = """
THIS IS A VALUE QUESTION. The user asks for a verdict or opinion ("should ...", "is it right ...", "is X good for the UK"). \
You never give a verdict, but you must NOT refuse and you must NOT reply that the sources don't answer it when they \
contain relevant case law or legislation. Answer with what the sources show, in this order:
(a) what the Court actually decided on the underlying legal issue, and its reasoning;
(b) the strongest sourced point on EACH side, each clearly attributed: "The Government argued ...", "The applicant \
argued ...", "The majority held ... because ...", "The dissenting / concurring judges considered ...", "Section N of the \
Act provides ...". Give each side at least one claim, and make the claims on one side as concrete as on the other;
(c) the relevant legislation or Convention text, if any is in the sources.
Where the sources contain no explicit arguments for and against (typical for questions about a statute), set out the two \
things the sources themselves put against each other, each with its citation: for example what the legislation empowers \
courts to do (section 3 interpretation, section 6 duties, section 8 remedies) against what it leaves to Parliament \
(section 4 declarations that do not strike legislation down, section 2 "take into account" rather than "be bound by", \
section 10 remedial orders), or the individual's Convention right against the State's margin of appreciation. \
Report positions as positions, never as your own view, and do not say which side is right. Use "message" for ONE short \
sentence only: "This asks for a value judgment, so this sets out what the sources show on each side without a verdict." \
Then go straight to the substance in the claims. Prefer 4 to 7 claims here.
"""


REWRITE_SYSTEM = """You write the one-sentence SHORT ANSWER to a question about the United Kingdom's case law at the \
European Court of Human Rights, using ONLY the numbered points the user gives you. Each point is a statement already \
checked against its source paragraph. You are a neutral research assistant: report what the Court held or did, never \
whether it was good or bad, and never whether the UK should stay in or leave the Convention.

RULES
1. ONE plain sentence of at most 240 characters, starting with the answer itself ("Not as a general rule: ...", \
"It depends on ...", or the holding: "In <case> the Court held that ..."). Match the reach of the points: when they \
decide particular applicants or circumstances and the question is general, do not open with "Yes" or "No" in any \
form ("Yes, where ...", "Yes, in some circumstances"); say whom or what the holding covered.
2. Build it from 1 to 3 points (never more). "based_on" lists their numbers. Name only cases that those points are about, and say \
only what those points say: no generalising ("always", "usually", "in many cases") and no reason, condition or fact \
that they do not state.
3. If the points cannot support a direct answer, reply {"short_answer": null}.

OUTPUT: only a JSON object: {"short_answer": {"text": "...", "based_on": [1, 2]}}"""


def rewrite_short_answer(
    conn, question: str, points: list[dict], failed: dict, request_id: str
) -> tuple[dict | None, llm.LLMResult | None]:
    """A second try at the short answer, built only from points that already passed verification.

    The model picks which points it summarises; the short answer cites those points' paragraphs
    (the first one each, so 3 as asked, 4 at most), so it cannot name a case it does not cite.
    -> (a new "short_answer" Claim dict with the failed claim's id, or None; the LLM result for cost)."""
    supported = [p for p in points if p["status"] == "supported" and p["citation_ids"]]
    if not supported:
        return None, None
    lines = "\n".join(f"{n}. {p['text']}" for n, p in enumerate(supported, 1))
    user = (
        f"Question: {question}\n\nChecked points:\n{lines}\n\n"
        f"A previous attempt was rejected: {failed['reason']}"
    )
    result = llm.complete(
        conn,
        model=config.verify_model(),
        system=REWRITE_SYSTEM,
        messages=[{"role": "user", "content": user}],
        purpose="generate",
        fake_key="short_rewrite",
        request_id=request_id,
        max_tokens=400,
    )
    try:
        raw = llm.parse_json_object(result.text).get("short_answer")
    except ValueError:
        return None, result
    if not isinstance(raw, dict) or not isinstance(raw.get("based_on"), list):
        return None, result
    chosen: list[dict] = []
    for n in raw["based_on"]:
        if isinstance(n, int) and 1 <= n <= len(supported) and supported[n - 1] not in chosen:
            chosen.append(supported[n - 1])
    ids = [p["citation_ids"][0] for p in chosen[:CLAIM_CITATIONS_MAX]]
    rebuilt = build_claims(
        [],
        set(ids),
        1,
        short_answer={"text": raw.get("text"), "citation_ids": list(dict.fromkeys(ids))},
        answer_first=True,
        short_answer_max_ids=CLAIM_CITATIONS_MAX,
    )
    if not rebuilt or not rebuilt[0]["citation_ids"]:
        return None, result
    return {**rebuilt[0], "id": failed["id"]}, result


def repair_id(raw: object, valid: set[str]) -> str | None:
    """Map a model-written citation id onto a real context id, or None if it can't be repaired."""
    s = re.sub(r"\s*§\s*", "§", str(raw).strip().strip("[]()<>.,;:'\" "))
    if s in valid:
        return s
    folded = {v.lower(): v for v in valid}
    if s.lower() in folded:
        return folded[s.lower()]
    bare = re.fullmatch(r"§?((?:op|u|art|s)?\d+)", s, re.IGNORECASE)
    if bare:  # model wrote just the paragraph number: accept only if it is unambiguous
        matches = [v for v in valid if v.lower().endswith("§" + bare.group(1).lower())]
        if len(matches) == 1:
            return matches[0]
    return None


def _trim_claim(text: str) -> str:
    text = one_line(text)
    if len(text) <= CLAIM_MAX_CHARS:
        return text
    cut = text[: CLAIM_MAX_CHARS - 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut).rstrip(" ,;:") + "…"


def _clean_group(raw: object) -> str | None:
    group = one_line(str(raw or "")).rstrip(" :")
    return group[:GROUP_MAX_CHARS].rstrip() or None


def build_claims(
    raw_claims: object,
    valid_ids: set[str],
    max_claims: int,
    *,
    short_answer: object = None,
    answer_first: bool = False,
    short_answer_max_ids: int = SHORT_ANSWER_CITATIONS_MAX,
) -> list[dict]:
    """Model claims -> contract Claim dicts. Unknown ids are repaired or dropped; a claim left with
    no valid id is kept but marked unsupported (so the UI can show what was rejected).

    With `answer_first`, the optional `short_answer` becomes the first claim (role "short_answer")
    and every other claim is a "point" carrying its optional `group` heading."""
    claims: list[dict] = []
    rows: list[object] = []
    if answer_first and isinstance(short_answer, dict):
        rows.append({**short_answer, "role": "short_answer"})
    if isinstance(raw_claims, list):
        rows.extend(raw_claims)
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        text = _trim_claim(str(raw.get("text") or ""))
        if not text:
            continue
        ids: list[str] = []
        candidates = raw.get("citation_ids") or []
        if isinstance(candidates, str):
            candidates = [candidates]
        for candidate in candidates:
            fixed = repair_id(candidate, valid_ids)
            if fixed and fixed not in ids:
                ids.append(fixed)
        is_short = answer_first and raw.get("role") == "short_answer"
        ids = ids[: short_answer_max_ids if is_short else CLAIM_CITATIONS_MAX]
        claim = {
            "id": f"c{len(claims) + 1}",
            "text": text,
            "citation_ids": ids,
            "status": "unverified" if ids else "unsupported",
            "reason": "Not yet verified." if ids else NO_VALID_CITATION,
        }
        if answer_first:
            claim["role"] = "short_answer" if raw.get("role") == "short_answer" else "point"
            group = _clean_group(raw.get("group")) if claim["role"] == "point" else None
            if group:
                claim["group"] = group
        claims.append(claim)
        if len(claims) >= max_claims:
            break
    return claims


def generate(
    conn,
    question: str,
    sources: list[Source],
    request_id: str,
    *,
    max_claims: int = 10,
    value_question: bool = False,
    answer_first: bool = False,
) -> tuple[list[dict], bool, str, dict | None]:
    """-> (claims, not_in_sources, message, StepCost dict or None when no model call was needed)."""
    if not sources:
        return [], True, NOT_IN_SOURCES_DEFAULT, None
    started = time.perf_counter()
    user = f"Question: {question}\n\nSources:\n\n{build_context(sources)}"
    messages = [{"role": "user", "content": user}]
    valid = {s.id for s in sources}
    answer_first = answer_first and not value_question
    system = SYSTEM_PROMPT
    if value_question:
        system += VALUE_RULES
    elif answer_first:
        system += ANSWER_FIRST_RULES
    tokens = {"tokens_in": 0, "tokens_out": 0, "tokens_cached": 0, "cost_usd": 0.0}
    claims: list[dict] = []
    parsed: dict = {}
    for attempt in range(2):
        result = llm.complete(
            conn,
            model=config.answer_model(),
            system=system,
            messages=messages,
            purpose="generate",
            request_id=request_id,
            max_tokens=2200 if answer_first else 1800,
        )
        tokens["tokens_in"] += result.tokens_in
        tokens["tokens_out"] += result.tokens_out
        tokens["tokens_cached"] += result.tokens_cached
        tokens["cost_usd"] += result.cost_usd
        retry_note = None
        try:
            parsed = llm.parse_json_object(result.text)
        except ValueError:
            if attempt == 1:
                raise
            retry_note = "That was not a valid JSON object. Reply with only the JSON object."
        else:
            claims = (
                []
                if parsed.get("not_in_sources")
                else build_claims(
                    parsed.get("claims"),
                    valid,
                    max_claims if not answer_first else min(max_claims, MAX_POINTS + 1),
                    short_answer=parsed.get("short_answer"),
                    answer_first=answer_first,
                )
            )
            if attempt == 0 and claims and not any(c["citation_ids"] for c in claims):
                log.warning("generate: no claim cited a listed source id; retrying once")
                retry_note = (
                    "None of your citation_ids matched a listed source. Copy each ID exactly as it "
                    "appears in the square brackets at the start of a source header (for example "
                    "001-12345§88 or 001-12345§op2), and reply with only the JSON object."
                )
        if retry_note is None:
            break
        messages = [
            *messages,
            {"role": "assistant", "content": result.text},
            {"role": "user", "content": retry_note},
        ]
    step = {
        "step": "generate",
        "model": config.answer_model(),
        **tokens,
        "latency_ms": (time.perf_counter() - started) * 1000,
    }
    message = one_line(str(parsed.get("message") or ""))[:CLAIM_MAX_CHARS]
    if not claims:
        return [], True, message or NOT_IN_SOURCES_DEFAULT, step
    return claims, False, message, step
