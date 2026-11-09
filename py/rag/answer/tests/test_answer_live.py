# ruff: noqa: E501
"""Live prompt-sanity checks (real Anthropic calls, a few cents each).

Run locally with: RUN_LIVE=1 uv run pytest rag/answer/tests/test_answer_live.py -s
Context is built from REAL snapshot paragraphs (crudely extracted from the stored HUDOC HTML, so
this test does not depend on the S2 parser).
"""

import json
import re

import pytest

from rag import config
from rag.answer import answer

pytestmark = pytest.mark.live

SNAP = config.REPO_ROOT / "data" / "snapshot"
MANIFEST = {e["item_id"]: e for e in json.loads((SNAP / "manifest.json").read_text())}
DEPORT = re.compile(r"deport|expel|expulsion|extradit|removal", re.IGNORECASE)

# (doc, explicit paragraph numbers or None for keyword-picked)
CASES = [
    ("001-57619", [88, 91, 111]),
    ("001-176931", None),
    ("001-85726", None),
    ("001-58004", None),
]


def numbered_paragraphs(item_id: str) -> dict[int, str]:
    html = (SNAP / "hudoc" / f"{item_id}.html").read_text()
    out: dict[int, str] = {}
    for raw in re.findall(r"<p[^>]*>(.*?)</p>", html, flags=re.S):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", raw).replace("\xa0", " ")).strip()
        m = re.match(r"(\d+)\.\s*(.+)", text)
        if m and int(m.group(1)) not in out:
            out[int(m.group(1))] = m.group(2)
    return out


@pytest.fixture
def real_context(answer_db, monkeypatch, fake_search):
    monkeypatch.setenv("LLM_MODE", "live")
    ids = []
    for item_id, wanted in CASES:
        e = MANIFEST[item_id]
        answer_db.execute("DELETE FROM documents WHERE item_id = %s", (item_id,))
        answer_db.execute(
            "INSERT INTO documents (item_id, case_name, doc_type, date, articles, outcome) VALUES (%s,%s,%s,%s,%s,%s)",
            (item_id, e["case_name"], e["doc_type"], e["date"], e["articles"], e["outcome"]),
        )
        paras = numbered_paragraphs(item_id)
        if wanted is None:
            scored = sorted(paras, key=lambda n: -len(DEPORT.findall(paras[n])))
            wanted = sorted(n for n in scored[:3] if DEPORT.search(paras[n]))
        for pos, n in enumerate(wanted):
            answer_db.execute(
                "INSERT INTO paragraphs (id, doc_id, position, number, section, text) VALUES (%s,%s,%s,%s,'The Law',%s)",
                (f"{item_id}§{n}", item_id, pos, n, paras[n]),
            )
            ids.append(f"{item_id}§{n}")
    answer_db.commit()
    fake_search["ids"] = ids
    return ids


def spend(conn) -> float:
    return float(conn.execute("SELECT coalesce(sum(cost_usd), 0) FROM cost_log").fetchone()[0])


def show(a, conn):
    print("\n---", a["question"])
    print(a["answer_text"])
    for c in a["claims"]:
        print(f"  {c['id']} [{c['status']}] {c['text']}  <- {c['citation_ids']}  ({c['reason']})")
    print(
        "steps:", [(s["step"], round(s["latency_ms"]), round(s["cost_usd"], 5)) for s in a["steps"]]
    )
    print(f"cost ${a['total_cost_usd']:.4f}; cost_log total in this test ${spend(conn):.4f}")


def test_deportation_answer_is_cited_and_balanced(answer_db, real_context):
    a = answer(
        answer_db,
        {
            "question": "Does the Convention stop the UK deporting criminals?",
            "options": {"route": "rag"},
        },
    )
    show(a, answer_db)
    assert a["claims"] and not a["refused_or_not_in_sources"]
    assert all(c["citation_ids"] for c in a["claims"]), "every claim must be cited"
    cited = {i for c in a["claims"] for i in c["citation_ids"]}
    assert cited <= set(real_context)
    assert sum(c["status"] == "supported" for c in a["claims"]) >= len(a["claims"]) // 2
    assert all(m in a["answer_text"] for m in re.findall(r"\[[^\]]+§[^\]]+\]", a["answer_text"]))
    assert a["total_cost_usd"] < 0.25


def test_opinion_question_gets_sourced_positions_and_no_opinion(answer_db, real_context):
    a = answer(
        answer_db, {"question": "Should the UK leave the ECHR?", "options": {"route": "rag"}}
    )
    show(a, answer_db)
    claims_text = " ".join(c["text"] for c in a["claims"]).lower()
    for phrase in (
        "should leave",
        "should remain",
        "should stay",
        "should withdraw",
        "i believe",
        "in my opinion",
        "i think",
        "would be better",
        "would be wise",
    ):
        assert phrase not in claims_text
    assert (
        "value judgment" in a["answer_text"].lower()
        or "do not give" in a["answer_text"].lower()
        or a["refused_or_not_in_sources"]
    )
    # either it declined (nothing in the sources) or everything it says is cited
    assert a["refused_or_not_in_sources"] or all(c["citation_ids"] for c in a["claims"])


def test_off_topic_question_is_not_answered_from_sources(answer_db, real_context):
    a = answer(
        answer_db, {"question": "What is the capital of Australia?", "options": {"route": "rag"}}
    )
    show(a, answer_db)
    assert a["refused_or_not_in_sources"] or not any(
        "canberra" in c["text"].lower() for c in a["claims"]
    )


def test_stats_params_extraction_and_router(answer_db, monkeypatch):
    from rag.answer import router, stats

    monkeypatch.setenv("LLM_MODE", "live")
    q3 = "How many UK deportation complaints in the corpus were declared inadmissible, and the most common reasons?"
    params, _ = stats.extract_params(answer_db, q3, "req-live")
    print("\nQ3 params:", params)
    assert params["group_by"] == "reason" and params["topic"] == "deportation"
    assert set(params["outcomes"]) <= {"inadmissible", "partly_inadmissible"} and params["outcomes"]
    params, _ = stats.extract_params(
        answer_db, "Per year, how many Article 8 judgments found a violation?", "req-live"
    )
    print("params:", params)
    assert (
        params["group_by"] == "year"
        and params["articles"] == ["8"]
        and params["outcomes"] == ["violation"]
    )
    assert (
        router.route(
            answer_db,
            "How often does the Court find a violation of Article 8 in UK cases?",
            "req-live",
        )
        == "stats"
    )
    assert (
        router.route(
            answer_db,
            "Which cases involve deportation of foreign criminals, and what did the Court say?",
            "req-live",
        )
        == "rag"
    )
