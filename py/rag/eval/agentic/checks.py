# ruff: noqa: E501
"""The per-answer metrics that need no model: agentic recall, verbatim-quote rate, shape checks."""

import re
import unicodedata
from collections.abc import Callable, Iterable

from .quotes import Checker, nested_variant, normalise, quote_in_any
from .text import ParsedAnswer, extract_quotes

NUMBER_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
    8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
    14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
    19: "nineteen", 20: "twenty",
}  # fmt: skip


def agentic_recall(gold: Iterable[str], fetched: Iterable[str]) -> float | None:
    """Share of the gold paragraphs among every paragraph id the model was shown. None without gold."""
    gold = set(gold)
    if not gold:
        return None
    return len(gold & set(fetched)) / len(gold)


def v2_gold(qrels) -> set[str]:
    """The qrels-v2 gold set: paragraphs graded 2 (as rag.eval.judging.metrics.gold_from_qrels)."""
    return {pid for pid, g in (qrels or {}).items() if g == 2}


def check_with_nesting(checker: Checker, pid: str, quote: str) -> dict:
    """check_quote, and if that fails once more with nested single quotation marks turned back into
    double ones ('in accordance with the law' for the Court's "in accordance with the law")."""
    result = checker(pid, quote)
    if result["verbatim"]:
        return result
    nested = nested_variant(quote)
    return checker(pid, nested) if nested != quote else result


def quote_report(
    parsed: ParsedAnswer,
    checker: Checker,
    *,
    shown: Iterable[str] = (),
    text_lookup: Callable[[str], str | None] | None = None,
) -> dict:
    """Every quoted passage in the answer, attributed to the paragraphs its claim cites and checked
    with check_quote. A quote whose claim cites nothing counts as not verbatim (nothing to check).

    With `shown` (the paragraph ids the model was shown) and `text_lookup`, each quote also gets
    `in_shown` / `in_shown_nocase`: is the text in *any* shown paragraph (exactly / ignoring case)?
    That separates "invented or altered" from "real but not attributed to a paragraph". The headline
    `quote_rate` is unchanged; `quote_rate_shown` is the second, looser figure (`in_shown_nocase`)."""
    shown = list(dict.fromkeys(shown))
    rows = []
    for claim in parsed.claims:
        for quote in extract_quotes(claim):
            attributed = claim["citation_ids"]
            results = {pid: check_with_nesting(checker, pid, quote) for pid in attributed}
            extra: dict = {}
            if text_lookup is not None:
                texts = [text_lookup(pid) for pid in shown]
                extra = {
                    "in_shown": quote_in_any(texts, quote),
                    "in_shown_nocase": quote_in_any(texts, quote, ignore_case=True),
                }
            rows.append(
                {
                    "claim_id": claim["id"],
                    "quote": quote,
                    "attributed_to": attributed,
                    "verbatim": any(r["verbatim"] for r in results.values()),
                    "best_similarity": max(
                        (r["similarity"] for r in results.values()), default=0.0
                    ),
                    **extra,
                }
            )
    rate = sum(r["verbatim"] for r in rows) / len(rows) if rows else None
    out = {"quotes": rows, "quote_rate": rate}
    if text_lookup is not None:
        out["quote_rate_shown"] = (
            sum(r["in_shown_nocase"] for r in rows) / len(rows) if rows else None
        )
    return out


def _first_words(text: str) -> str:
    return re.sub(r"^[\W_]+", "", text.replace("*", "").replace("_", " ")).lower()


QUALIFIER = re.compile(
    r"general rule|depends|in general|generally|in principle|only|not always|except|unless|"
    r"in some|in certain|but |not necessarily|subject to",
    re.IGNORECASE,
)


def no_bare_yes_no(answer_text: str) -> bool:
    """False if the answer opens with a bare Yes/No: its first sentence starts with the word and
    carries no qualification ("No, not as a general rule" is qualified; "No." and "Yes, it does" are bare)."""
    opening = _first_words(answer_text)
    if not re.match(r"(yes|no)\b", opening):
        return True
    first_sentence = re.split(r"(?<=[.!?])\s", opening, maxsplit=1)[0]
    return QUALIFIER.search(first_sentence) is not None


def _contains_number(text: str, n: int) -> bool:
    if re.search(rf"(?<![\d.,]){n}(?![\d]|[.,]\d)", text):
        return True
    word = NUMBER_WORDS.get(n)
    return bool(word and re.search(rf"\b{word}\b", text, re.IGNORECASE))


def _quote_norm(text: str) -> str:
    return normalise(unicodedata.normalize("NFKC", text)).lower()


def run_deterministic_check(
    check: dict,
    *,
    answer_text: str,
    parsed: ParsedAnswer,
    tool_names: list[str] | None,
    turn_tool_calls: int | None,
    route: str | None,
    quotes: dict,
) -> tuple[bool | None, str]:
    """-> (passed, detail). passed None = not applicable to this system."""
    kind = check["kind"]
    cited = parsed.cited_ids
    docs = {pid.split("§")[0] for pid in cited}
    if kind == "no_bare_yes_no":
        return no_bare_yes_no(answer_text), "opening words"
    if kind == "cites_min":
        return len(cited) >= check["n"], f"{len(cited)} distinct cited paragraphs"
    if kind == "distinct_cases_min":
        return len(docs) >= check["n"], f"{len(docs)} distinct cases cited"
    if kind == "mentions":
        hit = [w for w in check["any"] if w.lower() in answer_text.lower()]
        return bool(hit), f"found {hit}" if hit else f"none of {check['any']}"
    if kind == "tool_used":
        if tool_names is not None:
            return check["tool"] in tool_names, f"tools used: {sorted(set(tool_names))}"
        # /ask has no tools: its SQL stats route is the counterpart of count_cases
        return (route == "stats") if check["tool"] == "count_cases" else None, f"route {route}"
    if kind == "contains_numbers":
        missing = [n for n in check["snapshot"] if not _contains_number(answer_text, n)]
        return not missing, f"missing {missing}" if missing else "all numbers present"
    if kind == "cites_doc":
        return check["doc_id"] in docs, f"cited cases: {sorted(docs)}"
    if kind == "cites_paragraph":
        return check["paragraph_id"] in cited, "paragraph cited" if check[
            "paragraph_id"
        ] in cited else "not cited"
    if kind == "quotes_contain":
        wanted = _quote_norm(check["text"])
        ok = any(wanted in _quote_norm(q["quote"]) for q in quotes["quotes"])
        return ok, f"{len(quotes['quotes'])} quotes in the answer"
    if kind == "quotes_verbatim":
        bad = [q for q in quotes["quotes"] if not q["verbatim"]]
        return not bad, f"{len(quotes['quotes']) - len(bad)}/{len(quotes['quotes'])} verbatim"
    if kind == "new_tool_calls":
        if turn_tool_calls is None:
            return None, "no tools in /ask"
        return turn_tool_calls > 0, f"{turn_tool_calls} tool calls this turn"
    raise ValueError(f"unknown check kind {kind!r}")


JudgeChecks = Callable[[list[str]], list[bool | None]]


def shape_check(
    checks: list[dict],
    *,
    answer_text: str,
    parsed: ParsedAnswer,
    tool_names: list[str] | None,
    turn_tool_calls: int | None,
    route: str | None,
    quotes: dict,
    judge_checks: JudgeChecks | None,
) -> dict:
    """Run every check of an owner-review item. `judge` checks go to one judge call (judge_checks);
    pass = every applicable check passed (None = not applicable, or the judge was unavailable)."""
    results: list[dict] = []
    judge_idx = [i for i, c in enumerate(checks) if c["kind"] == "judge"]
    judged: list[bool | None] = (
        judge_checks([checks[i]["text"] for i in judge_idx])
        if judge_idx and judge_checks
        else [None] * len(judge_idx)
    )
    judged_by_index = dict(zip(judge_idx, judged, strict=True))
    for i, check in enumerate(checks):
        if check["kind"] == "judge":
            passed, detail = judged_by_index[i], check["text"]
        else:
            passed, detail = run_deterministic_check(
                check,
                answer_text=answer_text,
                parsed=parsed,
                tool_names=tool_names,
                turn_tool_calls=turn_tool_calls,
                route=route,
                quotes=quotes,
            )
        results.append({"kind": check["kind"], "passed": passed, "detail": detail})
    applicable = [r for r in results if r["passed"] is not None]
    unknown = [r for r in results if r["passed"] is None and r["kind"] == "judge"]
    return {
        "checks": results,
        "passed": all(r["passed"] for r in applicable) and not unknown if applicable else None,
    }
