"""Steps 3-4b: gold added / disputed counts, run-to-run agreement and the human review list."""

import re
from collections.abc import Mapping, Sequence

QUOTE_CHARS = 600


def grade_tables(pool: Sequence[dict], records: Mapping[str, dict]) -> dict:
    """Counts against the original key, over judged questions (run 1):
    gold_added = grade-2 paragraphs that were not original gold;
    gold_disputed_0 / gold_disputed_1 = original gold graded 0 / graded 1;
    gold_confirmed = original gold graded 2."""
    out = {"questions_judged": 0, "questions_failed": 0, "paragraphs": 0, "gold_total": 0,
           "gold_confirmed": 0, "gold_disputed_1": 0, "gold_disputed_0": 0, "gold_added": 0,
           "questions_with_added": 0, "grade_counts": {0: 0, 1: 0, 2: 0}}  # fmt: skip
    for q in pool:
        rec = records.get(q["question_id"])
        if rec is None or not rec["ok"]:
            out["questions_failed"] += 1
            continue
        out["questions_judged"] += 1
        added_here = 0
        for p in q["paragraphs"]:
            g = rec["grades"][p["id"]]["grade"]
            out["paragraphs"] += 1
            out["grade_counts"][g] += 1
            if p["gold"]:
                out["gold_total"] += 1
                out["gold_confirmed"] += g == 2
                out["gold_disputed_1"] += g == 1
                out["gold_disputed_0"] += g == 0
            elif g == 2:
                out["gold_added"] += 1
                added_here += 1
        out["questions_with_added"] += added_here > 0
    return out


def paired_grades(a: Mapping[str, dict], b: Mapping[str, dict]) -> list[dict]:
    """Every paragraph graded in both runs: {question_id, paragraph_id, g1, g2}."""
    out = []
    for qid in sorted(a):
        if qid in b and a[qid]["ok"] and b[qid]["ok"]:
            for pid, g in a[qid]["grades"].items():
                out.append(
                    {
                        "question_id": qid,
                        "paragraph_id": pid,
                        "g1": g["grade"],
                        "g2": b[qid]["grades"][pid]["grade"],
                    }
                )
    return out


def cohen_kappa(pairs: Sequence[tuple[int, int]]) -> float | None:
    """Unweighted Cohen's kappa for two label sequences; None if undefined (no pairs, or both
    raters used one label only)."""
    n = len(pairs)
    if not n:
        return None
    labels = sorted({x for p in pairs for x in p})
    po = sum(x == y for x, y in pairs) / n
    pe = sum(
        (sum(x == k for x, _ in pairs) / n) * (sum(y == k for _, y in pairs) / n) for k in labels
    )
    return None if pe == 1 else (po - pe) / (1 - pe)


def agreement(pairs: Sequence[dict]) -> dict:
    """Exact-grade agreement, Cohen's kappa, and agreement on 'grade 2 vs not'."""
    n = len(pairs)
    g = [(p["g1"], p["g2"]) for p in pairs]
    two = [(int(x == 2), int(y == 2)) for x, y in g]
    changed = [p for p in pairs if p["g1"] != p["g2"]]
    return {
        "paragraphs": n,
        "questions": len({p["question_id"] for p in pairs}),
        "exact": sum(x == y for x, y in g) / n if n else None,
        "kappa": cohen_kappa(g),
        "two_vs_not": sum(x == y for x, y in two) / n if n else None,
        "kappa_two_vs_not": cohen_kappa(two),
        "changed": len(changed),
        "changed_by_two": sum(abs(p["g1"] - p["g2"]) == 2 for p in changed),
    }


def trim(text: str, limit: int = QUOTE_CHARS) -> str:
    """A verbatim prefix of the paragraph, cut at a word boundary, marked when shortened."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " [...]"


def review_list(
    pool: Sequence[dict],
    run1: Mapping[str, dict],
    run2: Mapping[str, dict],
    n: int = 10,
    quotas: Mapping[str, int] | None = None,
) -> list[dict]:
    """About n items for a human to spot-check, chosen by a fixed rule (no randomness):
    (a) original gold graded 0: the judge may be wrong, or the key may be;
    (b) grade 2 on a paragraph that was not original gold: the added gold;
    (c) grade changed between the two runs: where the judge is unstable.
    Default quota 4 / 4 / 2 (shortfalls are filled from the other categories). Within a category,
    one item per question until every question has one, taking first the paragraphs found by the
    most configs (most 'retrievable'), so the list covers different questions and topics."""
    quotas = dict(quotas or {"gold_graded_0": 4, "added_gold": 4, "flipped": 2})
    candidates: dict[str, list[dict]] = {k: [] for k in quotas}
    for q in pool:
        r1, r2 = run1.get(q["question_id"]), run2.get(q["question_id"])
        if r1 is None or not r1["ok"]:
            continue
        for p in q["paragraphs"]:
            g1 = r1["grades"][p["id"]]
            g2 = r2["grades"][p["id"]] if r2 and r2["ok"] else None
            item = {
                "question_id": q["question_id"], "question": q["question"],
                "paragraph_id": p["id"], "case_name": p["case_name"], "section": p["section"],
                "quote": trim(p["text"]), "grade": g1["grade"], "reason": g1["reason"],
                "original_gold": p["gold"], "n_configs": p["n_configs"],
                "other_run_grade": g2["grade"] if g2 else None,
                "other_run_reason": g2["reason"] if g2 else None,
            }  # fmt: skip
            if p["gold"] and g1["grade"] == 0:
                candidates["gold_graded_0"].append({**item, "category": "gold_graded_0"})
            if not p["gold"] and g1["grade"] == 2:
                candidates["added_gold"].append({**item, "category": "added_gold"})
            if g2 is not None and g2["grade"] != g1["grade"]:
                size = abs(g2["grade"] - g1["grade"])
                candidates["flipped"].append({**item, "category": "flipped", "_size": size})
    chosen: list[dict] = []
    used: set[tuple[str, str]] = set()

    def take(cat: str, count: int) -> None:
        pool_c = sorted(
            candidates[cat],
            key=lambda i: (
                -i.get("_size", 0),
                -i["n_configs"],
                i["question_id"],
                i["paragraph_id"],
            ),
        )
        questions: set[str] = {c["question_id"] for c in chosen if c["category"] == cat}
        for second_pass in (False, True):
            for item in pool_c:
                if count <= 0:
                    return
                key = (item["question_id"], item["paragraph_id"])
                if key in used or (not second_pass and item["question_id"] in questions):
                    continue
                used.add(key)
                questions.add(item["question_id"])
                chosen.append({k: v for k, v in item.items() if not k.startswith("_")})
                count -= 1

    for cat, quota in quotas.items():
        take(cat, quota)
    for cat in quotas:  # fill any shortfall from the other categories
        take(cat, n - len(chosen))
    return chosen[:n]


_STOP = frozenset(
    {"states", "state", "about", "this", "that", "with", "from", "which", "where", "their", "there"}
    | {"court", "para", "paragraph", "question", "answer", "directly", "holds", "hold"}
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{5,}", text.lower()) if w not in _STOP}


def reason_mismatches(
    pool: Sequence[dict], records: Mapping[str, dict], grade: int = 2
) -> list[dict]:
    """A cheap check that a judge's reason belongs to the paragraph it was attached to: grade-
    `grade` paragraphs whose reason shares no content word (5+ letters) with the paragraph text.
    A hit means the judge probably wrote the reason for another paragraph. It misses subtler
    mix-ups, so it is a smoke alarm, not a proof of alignment."""
    out = []
    for q in pool:
        rec = records.get(q["question_id"])
        if rec is None or not rec["ok"]:
            continue
        for p in q["paragraphs"]:
            g = rec["grades"][p["id"]]
            reason_words = _words(g["reason"])
            if g["grade"] == grade and reason_words and not (reason_words & _words(p["text"])):
                out.append({"question_id": q["question_id"], "paragraph_id": p["id"],
                            "reason": g["reason"]})  # fmt: skip
    return out
