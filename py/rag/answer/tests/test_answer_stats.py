# ruff: noqa: E501
import psycopg
import pytest

from rag.answer import stats
from rag.contract import contract_errors

Q3 = (
    "How many UK deportation complaints in the corpus were declared inadmissible, "
    "and the most common reasons?"
)


def test_q3_counts_and_reasons(answer_db):
    result = stats.run_stats(answer_db, Q3, "req-t")
    assert contract_errors("StatsQueryResult", result) == []
    # Horne and Osagiede match. Khaksar is only *partly* inadmissible (not counted, but reported),
    # Smith is not about removal, and Field and Others uses the word "expulsion" but raises none of
    # Articles 3, 8 or 5(1)(f), so it is not a deportation complaint.
    assert result["count"] == 2
    rows = dict(map(tuple, result["rows"]))
    assert rows == {"manifestly_ill_founded": 1, "non_exhaustion": 1}
    assert result["columns"] == ["reason", "documents"]
    assert {c["doc_id"] for c in result["matching_cases"]} == {"001-200001", "001-200002"}
    assert "1 further matching decision(s) were only partly inadmissible" in result["explanation"]


def test_deportation_definition_is_stated_and_uses_articles(answer_db):
    result = stats.run_stats(answer_db, Q3, "req-t")
    assert "Article 3, 8, 5(1)(f)" in result["explanation"]
    assert "split_part(a, '-', 1) IN ('3', '8', '5-1-f')" in result["sql"]
    names = {c["case_name"] for c in result["matching_cases"]}
    assert not any("Field" in n for n in names)


def test_sql_shown_is_the_sql_run_and_defines_topic(answer_db):
    result = stats.run_stats(answer_db, Q3, "req-t")
    sql = result["sql"]
    assert "paragraphs" in sql and "~*" in sql and "deport" in sql and "extradit" in sql
    assert "'inadmissible'" in sql and "inadmissibility_grounds" in sql
    assert len(sql) <= 1500
    stats.validate_readonly_select(sql.split(";\n")[0])
    assert "text match" in result["explanation"] or "text" in result["explanation"]
    assert "deport" in result["explanation"]


def test_matching_case_quotes_are_verbatim_and_link(answer_db):
    result = stats.run_stats(answer_db, Q3, "req-t")
    for c in result["matching_cases"]:
        text = answer_db.execute(
            "SELECT text FROM paragraphs WHERE id = %s", (c["paragraph_id"],)
        ).fetchone()[0]
        assert c["quote"] in text
        assert c["link_target"].startswith(f"/case/{c['doc_id']}#p")


def test_other_groupings(answer_db):
    by_article = stats.run_stats_full(
        answer_db, "Which article by article, deportation cases?", "r"
    )
    assert by_article.result["columns"] == ["article", "documents"]
    plain = stats.run_stats(answer_db, "How many deportation judgments are there?", "r")
    assert plain["columns"] == ["documents"]
    assert plain["count"] == 1  # Soering only: Jones and N. v UK have a single matching paragraph


@pytest.mark.parametrize(
    "bad",
    [
        "INSERT INTO documents (item_id) VALUES ('x')",
        "UPDATE documents SET outcome = 'x'",
        "DELETE FROM paragraphs",
        "DROP TABLE documents",
        "SELECT 1; DROP TABLE documents",
        "SELECT * FROM cost_log",
        "SELECT * FROM pg_shadow",
        "SELECT * FROM documents INTO newtable",
        "WITH x AS (DELETE FROM documents RETURNING *) SELECT * FROM x",
        "SELECT * FROM documents FOR UPDATE",
        "SELECT * FROM secret_table",
        "SELECT pg_sleep(10)",
        "COPY documents TO '/tmp/x'",
    ],
)
def test_validator_rejects_everything_but_whitelisted_selects(bad):
    with pytest.raises(ValueError):
        stats.validate_readonly_select(bad)


def test_validator_accepts_template_sql():
    stats.validate_readonly_select(
        "WITH m AS (SELECT item_id FROM documents d WHERE d.outcome IN ('inadmissible'))\n"
        "SELECT count(*) FROM m LEFT JOIN LATERAL unnest(ARRAY[1]) AS g ON true"
    )


def test_write_attempt_fails_even_without_the_validator(answer_db, monkeypatch):
    """Second line of defence: the transaction itself is READ ONLY."""
    before = answer_db.execute("SELECT count(*) FROM documents").fetchone()[0]
    with pytest.raises(ValueError):
        stats.execute_readonly(answer_db, "DELETE FROM documents")
    monkeypatch.setattr(stats, "validate_readonly_select", lambda sql: None)
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        stats.execute_readonly(answer_db, "DELETE FROM documents")
    answer_db.rollback()
    assert answer_db.execute("SELECT count(*) FROM documents").fetchone()[0] == before


def test_statement_timeout(answer_db):
    sql = "SELECT count(*) FROM generate_series(1, 100000000) a"  # would run for seconds
    with pytest.raises(psycopg.errors.QueryCanceled):
        stats.execute_readonly(answer_db, sql, timeout_ms=50)
    answer_db.rollback()


def test_params_are_sanitized():
    raw = {
        "group_by": "drop table",
        "topic": "x'; DROP TABLE documents; --",
        "keywords": ["fine words", "bad'; --", 7],
        "articles": ["8", "8; DROP", "P1-1"],
        "doc_types": ["decision", "evil"],
        "outcomes": "inadmissible",
        "date_from": "2020-13-45",
        "date_to": "2021-01-01",
    }
    p = stats.sanitize_params(raw)
    assert p["group_by"] == "none" and p["topic"] is None
    assert p["keywords"] == ["fine words"]
    assert p["articles"] == ["8", "P1-1"]
    assert p["doc_types"] == ["decision"] and p["outcomes"] == ["inadmissible"]
    assert p["date_from"] is None and p["date_to"] == "2021-01-01"


def test_injection_through_params_is_quoted(answer_db):
    params = stats.sanitize_params({"keywords": ["o'brien"], "articles": ["8"]})
    query = stats.build_query(answer_db, params)  # keyword pattern rejects the quote
    assert "o'brien" not in query.prefix
    params["date_from"] = "2020-01-01"
    query = stats.build_query(answer_db, params)
    stats.validate_readonly_select(f"{query.prefix}\nSELECT count(*) FROM matched")


# --- one test per mismatch found by the judged eval (stat accuracy 6/12) ------------------------


def run(conn, question):
    return stats.run_stats(conn, question, "req-t")


def test_grand_chamber_filter_is_applied(answer_db):
    r = run(answer_db, "How many Grand Chamber judgments about the UK are in the corpus?")
    assert r["count"] == 2  # Gamma and Delta; the ordinary Chamber judgments are not counted
    assert "chamber IN ('Grand Chamber')" in r["sql"].replace("d.chamber", "chamber")
    assert "Grand Chamber" in r["explanation"]


def test_at_least_one_violation_includes_mixed(answer_db):
    r = run(answer_db, "How many UK judgments in the corpus found at least one violation?")
    # violation: Soering, Jones, Delta; mixed: Gamma. no_violation (N., Epsilon) is not counted.
    assert r["count"] == 4
    assert "'violation', 'mixed'" in r["sql"]
    assert "mixed" in r["explanation"] and "no-violation" in r["explanation"]


def test_most_common_ground_returns_that_grounds_count_not_the_total(answer_db):
    q = "What is the most common inadmissibility ground among UK decisions, and how many decisions rest on it?"
    r = run(answer_db, q)
    # inadmissible decisions: Horne (mif), Osagiede (non_ex), Smith (out_of_time), Zeta (mif), Field (ratione materiae)
    assert r["rows"][0] == ["manifestly_ill_founded", 2]
    assert r["count"] == 2
    assert "2 of the 5 matching" in r["explanation"]
    assert {c["doc_id"] for c in r["matching_cases"]} == {"001-200001", "001-200006"}


def test_declared_inadmissible_means_whole_application_and_says_so(answer_db):
    r = run(answer_db, "How many UK decisions in the corpus were declared inadmissible?")
    assert r["count"] == 5  # not Khaksar (partly_inadmissible)
    assert "'inadmissible'" in r["sql"] and "partly_inadmissible" not in r["sql"]
    assert "whole application" in r["explanation"]
    assert "1 further matching decision(s) were only partly inadmissible" in r["explanation"]
    r = run(
        answer_db, "How many decisions were declared inadmissible in whole or partly inadmissible?"
    )
    assert "partly_inadmissible" in r["sql"] and r["count"] == 6


def test_non_exhaustion_deportation_count(answer_db):
    q = "How many deportation or expulsion decisions were declared inadmissible because the applicant had not exhausted domestic remedies?"
    r = run(answer_db, q)
    assert r["count"] == 1  # Osagiede; Khaksar's partial inadmissibility is reported, not counted
    assert "non_exhaustion" in r["sql"]


def _full(conn, question):
    return stats.run_stats_full(conn, question, "req-t")


def test_count_sentence_is_natural_and_claims_match_it_verbatim(answer_db):
    run_ = _full(answer_db, Q3)
    first = run_.answer_text.split(" Most common reasons:")[0]
    assert first == (
        "The indexed corpus has 2 judgments and decisions about deportation, expulsion, "
        "removal or extradition that were declared inadmissible."
    )
    assert "are in the indexed corpus" not in run_.answer_text
    assert run_.claims[0]["text"] == first
    # every claim is, word for word, a sentence of the answer text
    for claim in run_.claims:
        assert claim["text"] in run_.answer_text


def test_sentence_names_the_ground_filter_it_applied(answer_db):
    q = "How many deportation or expulsion decisions were declared inadmissible because the applicant had not exhausted domestic remedies?"
    run_ = _full(answer_db, q)
    assert run_.params["grounds"] == ["non_exhaustion"]
    assert run_.claims[0]["text"] == (
        "The indexed corpus has 1 judgment or decision about deportation, expulsion, removal "
        "or extradition that was declared inadmissible for non-exhaustion of domestic remedies."
    )
    assert "non-exhaustion of domestic remedies" in run_.claims[0]["text"]
    assert run_.claims[0]["text"] in run_.answer_text
    assert "non_exhaustion" in run_.result["sql"]  # the SQL filter the sentence describes


def test_every_filter_in_the_sql_appears_in_the_sentence(answer_db):
    params = stats.sanitize_params(
        {
            "topic": "deportation",
            "articles": ["8"],
            "doc_types": ["decision"],
            "outcomes": ["inadmissible"],
            "grounds": ["non_exhaustion", "out_of_time"],
            "chambers": ["Committee"],
            "date_from": "2000-01-01",
            "date_to": "2020-12-31",
        }
    )
    query = stats.build_query(answer_db, params)
    scope = stats._scope_phrase(params, query)
    for fragment in (
        "admissibility decisions",
        "deportation, expulsion, removal or extradition",
        "Committee",
        "Article 8",
        "between 2000-01-01 and 2020-12-31",
        "declared inadmissible for non-exhaustion of domestic remedies or being out of time",
    ):
        assert fragment in scope
    assert "_" not in scope  # no raw enum keys


def test_singular_and_violation_wording(answer_db):
    params = stats.sanitize_params({"outcomes": ["violation", "mixed"], "doc_types": ["judgment"]})
    query = stats.build_query(answer_db, params)
    assert (
        stats._scope_phrase(params, query, plural=False)
        == "judgment that found at least one violation"
    )


# --- "how many X, and how many of them Y", and honest example clauses ------------------------------------------

GC_QUESTION = (
    "How many Grand Chamber judgments are in the corpus, and how many of them found a violation?"
)
# Operative provisions modelled on the snapshot cases whose first clause misled the reader.
GC_CASES = [
    # (item_id, name, outcome, date, operative clauses)
    (
        "001-400001",
        "Skeini-like v. The United Kingdom",
        "violation",
        "2011-07-07",
        [
            "Dismisses the Government's preliminary objection that the applicants' relatives did not fall within the jurisdiction of the respondent State;",
            "Holds that there has been a violation of the procedural obligation under Article 2 of the Convention;",
        ],
    ),
    (
        "001-400002",
        "Jedda-like v. The United Kingdom",
        "violation",
        "2011-07-06",
        [
            "Joins to the merits the Government's preliminary objection concerning jurisdiction and declares the application admissible;",
            "Holds that there has been a violation of Article 5 \u00a7 1 of the Convention;",
        ],
    ),
    (
        "001-400003",
        "A. and Others-like v. The United Kingdom",
        "mixed",
        "2009-02-19",
        [
            "Declares the applications admissible, except for the complaints of the fourth and seventh applicants;",
            "Holds that there has been no violation of Article 3 of the Convention, taken alone or in conjunction with Article 13;",
            "Holds that there has been a violation of Article 5 \u00a7 1 of the Convention in respect of the first, third and fifth applicants;",
        ],
    ),
    (
        "001-400004",
        "Saadi-like v. The United Kingdom",
        "mixed",
        "2008-01-29",
        [
            "Holds by eleven votes to six that there has been no violation of Article 5 \u00a7 1 of the Convention;",
            "Holds unanimously that there has been a violation of Article 5 \u00a7 2 of the Convention;",
        ],
    ),
    (
        "001-400005",
        "Objection-only v. The United Kingdom",
        "violation",
        "2007-01-01",
        [
            "Dismisses the Government's preliminary objection;",
            "Holds that it is not necessary to examine whether there has been a violation of Article 14;",
        ],
    ),
    (
        "001-400006",
        "Upheld v. The United Kingdom",
        "no_violation",
        "2006-01-01",
        [
            "Holds that there has been no violation of Article 8 of the Convention;",
        ],
    ),
]


@pytest.fixture
def gc_db(answer_db):
    for item_id, name, outcome, date, clauses in GC_CASES:
        answer_db.execute(
            "INSERT INTO documents (item_id, case_name, doc_type, date, articles, outcome, chamber) "
            "VALUES (%s, %s, 'judgment', %s, %s, %s, 'Grand Chamber')",
            (item_id, name, date, ["5"], outcome),
        )
        for i, text in enumerate(clauses, 1):
            answer_db.execute(
                "INSERT INTO paragraphs (id, doc_id, position, section, text) VALUES (%s, %s, %s, %s, %s)",
                (f"{item_id}\u00a7op{i}", item_id, 100 + i, "Operative provisions", text),
            )
    answer_db.commit()
    return answer_db


def test_total_and_subset_are_both_stated(gc_db):
    run_ = _full(gc_db, GC_QUESTION)
    # Grand Chamber judgments: Gamma (mixed), Delta (violation) + the six above; Upheld found no violation.
    assert run_.result["scope_total"] == 8
    assert run_.result["count"] == 7
    assert run_.claims[0]["text"] == (
        "The indexed corpus has 8 Grand Chamber judgments; 7 of them found at least one violation."
    )
    assert run_.answer_text.startswith(run_.claims[0]["text"])
    assert "in formation" not in run_.answer_text
    assert "UK" not in run_.claims[0]["text"]  # no respondent filter was asked for or applied
    assert run_.result["rows"] == [
        ["Grand Chamber judgments", 8],
        ["Found at least one violation", 7],
    ]
    sql = run_.result["sql"]
    assert sql.count("WITH matched AS") == 2 and "'violation', 'mixed'" in sql
    assert (
        "formation" in run_.result["explanation"]
    )  # what the chamber field means stays in the explanation
    assert contract_errors("StatsQueryResult", run_.result) == []


def test_single_count_questions_have_no_scope_total(answer_db):
    r = run(answer_db, "How many UK judgments in the corpus found at least one violation?")
    assert r["scope_total"] is None


def test_examples_quote_the_violation_clause_never_a_contradictory_one(gc_db):
    run_ = _full(gc_db, GC_QUESTION)
    cases = {c["doc_id"]: c for c in run_.result["matching_cases"]}
    assert "001-400006" not in cases  # no violation: not in the violation list
    for doc_id in ("001-400001", "001-400002", "001-400003", "001-400004"):
        c = cases[doc_id]
        assert c["paragraph_id"] is not None and c["quote"]
        assert "there has been a violation" in c["quote"], c
        for wrong in ("objection", "merits", "admissible", "no violation"):
            assert wrong not in c["quote"], (doc_id, c["quote"])
    assert (
        cases["001-400001"]["paragraph_id"] == "001-400001\u00a7op2"
    )  # not the preliminary objection
    assert (
        cases["001-400002"]["paragraph_id"] == "001-400002\u00a7op2"
    )  # not the join to the merits
    assert (
        cases["001-400003"]["paragraph_id"] == "001-400003\u00a7op3"
    )  # not admissibility, not no-violation
    assert (
        cases["001-400004"]["paragraph_id"] == "001-400004\u00a7op2"
    )  # mixed: the violation clause
    # no honest clause ("not necessary to examine whether there has been a violation"): listed, not quoted
    bare = cases["001-400005"]
    assert bare["paragraph_id"] is None and bare["quote"] == ""
    assert bare["link_target"] == "/case/001-400005"
    assert bare["doc_type"] == "judgment"


def test_examples_do_not_prove_the_count(gc_db):
    run_ = _full(gc_db, GC_QUESTION)
    assert all(
        c["citation_ids"] == [] for c in run_.claims
    )  # the evidence for the count is the SQL
    assert "illustrate" in run_.result["explanation"]
    assert "without a quote" in run_.result["explanation"]
    from rag.answer.pipeline import stats_citations

    cited = stats_citations(run_.result)
    assert all(c["paragraph_id"] for c in cited)
    assert "001-400005" not in {c["doc_id"] for c in cited}
    assert all(
        set(c) == {"paragraph_id", "doc_id", "case_name", "doc_type", "quote", "link_target"}
        for c in cited
    )


@pytest.mark.parametrize(
    "clauses, kind, expected",
    [
        (
            [
                "Dismisses the Government's preliminary objection;",
                "Holds that there has been a violation of Article 2;",
            ],
            "violation",
            1,
        ),
        (
            [
                "Joins to the merits the preliminary objection;",
                "Holds that there has been a violation of Article 5;",
            ],
            "violation",
            1,
        ),
        (
            [
                "Declares the application admissible;",
                "Holds that there would be a violation of Article 3 in the event of the applicant's deportation;",
            ],
            "violation",
            1,
        ),
        (
            [
                "Holds that there has been no violation of Article 5 \u00a7 1;",
                "Holds that there has been a violation of Article 5 \u00a7 4;",
            ],
            "violation",
            1,
        ),
        (["Holds that there has been no violation of Article 5 \u00a7 1;"], "violation", None),
        (
            [
                "Holds that it is not necessary to examine whether there has been a violation of Article 14;"
            ],
            "violation",
            None,
        ),
        (
            [
                "Holds that there has been a violation of Article 8;",
                "Holds that there has been no violation of Article 3;",
            ],
            "no_violation",
            1,
        ),
    ],
)
def test_pick_operative_clause(clauses, kind, expected):
    paragraphs = [(f"x\u00a7op{i}", t) for i, t in enumerate(clauses)]
    picked = stats.pick_operative_clause(paragraphs, kind)
    assert (
        (picked and paragraphs.index(picked)) == expected
        if expected is not None
        else picked is None
    )


def test_operative_clause_prefers_the_requested_article():
    paragraphs = [
        ("x\u00a7op1", "Holds that there has been a violation of Article 5 \u00a7 1;"),
        ("x\u00a7op2", "Holds that there has been a violation of Article 8;"),
    ]
    assert stats.pick_operative_clause(paragraphs, "violation", ["8"])[0] == "x\u00a7op2"
