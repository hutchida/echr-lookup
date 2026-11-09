# ruff: noqa: E501
"""The statistics path: counting questions are answered by SQL over the metadata tables.

Safety first: the model never writes SQL. It only extracts *parameters* (article, outcome, topic ...)
that are validated against fixed lists and slotted into a parameterised template. The finished SQL is
then checked again (single SELECT, whitelisted tables) and run in a READ ONLY transaction with a 3 s
statement timeout, so even a bug cannot write or hang the database. The SQL that ran is returned, so
the reader can audit every number.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import psycopg

from rag import config
from rag.answer import citations as cit
from rag.answer import llm
from rag.answer.context import local_step, one_line

STATEMENT_TIMEOUT_MS = 3000
ROWS_MAX = 20
CASES_MAX = 8
CELL_MAX_CHARS = 80
SQL_MAX_CHARS = 1500
EXPLANATION_MAX_CHARS = 1000
TOPIC_MIN_PARAGRAPHS = (
    3  # keyword-only topics: a document is "about" it if >= this many paragraphs match
)

ALLOWED_TABLES = {"documents", "paragraphs", "chunks"}
ALLOWED_FUNCTIONS = {"unnest", "generate_series"}

GROUP_BY = ("none", "reason", "article", "outcome", "year", "doc_type")
DOC_TYPES = ("judgment", "decision", "communicated", "legal_summary", "legislation")
OUTCOMES = (
    "violation",
    "no_violation",
    "mixed",
    "inadmissible",
    "partly_inadmissible",
    "struck_out",
    "admissible",
    "other",
    "not_applicable",
)
GROUNDS = (
    "manifestly_ill_founded",
    "non_exhaustion",
    "out_of_time",
    "incompatible_ratione_materiae",
    "incompatible_ratione_personae",
    "incompatible_ratione_temporis",
    "incompatible_ratione_loci",
    "abuse_of_right",
    "no_significant_disadvantage",
    "substantially_same",
    "not_a_victim",
    "other",
)
GROUND_LABELS = {
    "manifestly_ill_founded": "manifestly ill-founded",
    "non_exhaustion": "domestic remedies not exhausted",
    "out_of_time": "out of time (six-month rule)",
    "incompatible_ratione_materiae": "outside the Convention's subject matter",
    "incompatible_ratione_personae": "outside the Convention as to persons",
    "incompatible_ratione_temporis": "outside the Convention as to time",
    "incompatible_ratione_loci": "outside the Convention as to territory",
    "abuse_of_right": "abuse of the right of application",
    "no_significant_disadvantage": "no significant disadvantage",
    "substantially_same": "substantially the same as an earlier application",
    "not_a_victim": "applicant not a victim",
    "other": "another stated ground",
}
# "Deportation" is a definition, not a metadata field: the document must raise a Convention article
# that governs removal (3: risk of ill-treatment abroad; 8: family and private life; 5-1-f: detention
# pending deportation) AND discuss removal in at least `min_paragraphs` paragraphs. The article test
# keeps out documents that merely contain the words (e.g. "expulsion from the House of Lords").
TOPICS = {
    "deportation": {
        "label": "deportation, expulsion, removal or extradition",
        "keywords": ("deport", "expel", "expulsion", "extradit", "removal"),
        "articles": ("3", "8", "5-1-f"),
        "min_paragraphs": 2,
    }
}
CHAMBERS = ("Grand Chamber", "Chamber", "Committee")
COUNT_OF = ("total", "top_group", "total_and_subset")
# Court documents only by default: legal summaries re-describe judgments/decisions and legislation
# has no outcome, so including them would double count.
DEFAULT_DOC_TYPES = ("judgment", "decision", "communicated")
INADMISSIBLE = ("inadmissible", "partly_inadmissible")

PARAMS_SYSTEM = (
    """You turn a counting question about UK cases at the European Court of Human Rights \
into parameters for a fixed SQL template. Reply with only a JSON object with these keys (omit or use \
null/[] for anything the question does not say):
{
 "group_by": "none" | "reason" | "article" | "outcome" | "year" | "doc_type",
 "topic": "deportation" | null,
 "keywords": [],
 "articles": [],
 "doc_types": [],
 "outcomes": [],
 "chambers": [],
 "grounds": [],
 "count_of": "total",
 "date_from": null,
 "date_to": null
}
- group_by "reason": the question asks WHY applications were inadmissible (reasons / grounds). "article": \
which Convention articles. "year": per year / over time. "outcome": breakdown by result. "none": just a count.
- topic "deportation": the question is about deportation, expulsion, removal or extradition.
- keywords: other subject words to find in the text (lower-case, at most 4). Every case in the corpus is a UK case, so never use "uk" or "united kingdom"; do not repeat the topic's words; usually leave empty.
- articles: Convention article numbers as strings, e.g. "3", "8", "P1-1".
- doc_types from: judgment, decision, legal_summary. Leave empty unless the question names a type.
- outcomes from: violation, no_violation, mixed, inadmissible, partly_inadmissible, struck_out, admissible. \
Meanings: "violation" = judgments with only violation findings; "no_violation" = only no-violation findings; \
"mixed" = at least one violation AND at least one no-violation finding; "inadmissible" = the whole application was \
declared inadmissible; "partly_inadmissible" = only part of it. So "found a violation" / "at least one violation" / \
"any violation" = ["violation", "mixed"]. "Declared inadmissible" = ["inadmissible"] only; add \
"partly_inadmissible" only if the question says partly / in whole or in part.
- chambers from: "Grand Chamber", "Chamber", "Committee" (a Grand Chamber judgment is chamber "Grand Chamber"; \
"Chamber" means the ordinary Chamber, not the Grand Chamber).
- count_of: "total" normally (the number of matching documents). Use "top_group" only when the question asks how \
many documents fall in the most common group, e.g. "the most common inadmissibility ground and how many decisions \
rest on it" (then group_by is "reason"). Use "total_and_subset" when the question asks for a total AND how many of \
those have an outcome, e.g. "How many Grand Chamber judgments are there, and how many of them found a violation?" \
(put that outcome in outcomes; the total is counted without it).
- grounds (only if the question restricts to some inadmissibility ground) from: """
    + ", ".join(GROUNDS)
    + """.
- date_from / date_to: ISO dates (YYYY-MM-DD) if the question gives a period."""
)


class StatsError(RuntimeError):
    """The statistics path could not produce a result."""


# --------------------------------------------------------------------------------------------
# SQL safety
# --------------------------------------------------------------------------------------------

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|do|execute|vacuum|"
    r"set|reset|begin|commit|rollback|lock|listen|notify|into|prepare|merge|"
    r"cost_log|eval_runs|ingest_runs|schema_migrations|"
    r"information_schema|current_setting|set_config|dblink|pg_\w+|lo_\w+)\b",
    re.IGNORECASE,
)
_FOR_LOCK = re.compile(r"\bfor\s+(update|share|no\s+key\s+update|key\s+share)\b", re.IGNORECASE)
_TABLE_REF = re.compile(
    r"\b(?:from|join)\s+(?:lateral\s+)?([a-z_][a-z0-9_.]*)\s*(\()?", re.IGNORECASE
)
_CTE_NAME = re.compile(r"(?:\bwith|,)\s*([a-z_][a-z0-9_]*)\s+as\s*\(", re.IGNORECASE)


def validate_readonly_select(sql: str) -> None:
    """Raise ValueError unless `sql` is ONE read-only SELECT over the whitelisted tables."""
    no_strings = re.sub(r"'(?:[^']|'')*'", "''", sql)
    no_comments = re.sub(r"--[^\n]*|/\*.*?\*/", " ", no_strings, flags=re.DOTALL)
    body = no_comments.strip().rstrip(";").strip()
    if ";" in body:
        raise ValueError("only a single SQL statement is allowed")
    if not re.match(r"(select|with)\b", body, re.IGNORECASE):
        raise ValueError("only SELECT statements are allowed")
    if bad := _FORBIDDEN.search(body):
        raise ValueError(f"forbidden SQL keyword or object: {bad.group(1)}")
    if _FOR_LOCK.search(body):
        raise ValueError("row locking clauses are not allowed")
    ctes = {m.lower() for m in _CTE_NAME.findall(body)}
    for name, call in _TABLE_REF.findall(body):
        name = name.lower()
        if call:
            if name not in ALLOWED_FUNCTIONS:
                raise ValueError(f"function not allowed in FROM: {name}")
        elif name not in ALLOWED_TABLES and name not in ctes:
            raise ValueError(f"table not allowed: {name}")


def execute_readonly(
    conn, sql: str, *, timeout_ms: int = STATEMENT_TIMEOUT_MS
) -> tuple[list[str], list[tuple]]:
    """Validate, then run `sql` inside a rolled-back READ ONLY transaction with a statement timeout."""
    validate_readonly_select(sql)
    with conn.transaction(force_rollback=True):
        conn.execute("SET LOCAL transaction_read_only = on")
        conn.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
        cur = conn.execute(sql)
        columns = [c.name for c in cur.description or []]
        return columns, cur.fetchall()


# --------------------------------------------------------------------------------------------
# Parameters (model extracts, we validate)
# --------------------------------------------------------------------------------------------

_KEYWORD = re.compile(r"[a-z][a-z \-]{2,30}")
_ARTICLE = re.compile(r"(?:P\d+-)?\d{1,2}")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def sanitize_params(raw: dict) -> dict:
    """Keep only values from the fixed lists / patterns; drop everything else."""

    def pick(key: str, allowed: tuple[str, ...]) -> list[str]:
        values = raw.get(key) or []
        values = [values] if isinstance(values, str) else values
        return [v for v in dict.fromkeys(values) if isinstance(v, str) and v in allowed]

    def iso(key: str) -> str | None:
        value = raw.get(key)
        if isinstance(value, str) and _ISO_DATE.fullmatch(value):
            try:
                date.fromisoformat(value)
            except ValueError:
                return None
            return value
        return None

    keywords = [
        k.strip().lower()
        for k in (raw.get("keywords") or [])
        if isinstance(k, str)
        and _KEYWORD.fullmatch(k.strip().lower())
        and k.strip().lower() not in ("uk", "united kingdom", "the united kingdom", "britain")
    ]
    articles = [
        str(a).strip()
        for a in (raw.get("articles") or [])
        if isinstance(a, str | int) and _ARTICLE.fullmatch(str(a).strip())
    ]
    group_by = raw.get("group_by") if raw.get("group_by") in GROUP_BY else "none"
    return {
        "group_by": group_by,
        "topic": raw.get("topic") if raw.get("topic") in TOPICS else None,
        "keywords": keywords[:4],
        "articles": list(dict.fromkeys(articles))[:5],
        "doc_types": pick("doc_types", DOC_TYPES),
        "outcomes": pick("outcomes", OUTCOMES),
        "grounds": pick("grounds", GROUNDS),
        "chambers": pick("chambers", CHAMBERS),
        "count_of": raw.get("count_of") if raw.get("count_of") in COUNT_OF else "total",
        "date_from": iso("date_from"),
        "date_to": iso("date_to"),
    }


def extract_params(conn, question: str, request_id: str) -> tuple[dict, llm.LLMResult]:
    result = llm.complete(
        conn,
        model=config.router_model(),
        system=PARAMS_SYSTEM,
        messages=[{"role": "user", "content": f"Question: {question}"}],
        purpose="generate",
        fake_key="stats_params",
        request_id=request_id,
        max_tokens=400,
    )
    try:
        raw = llm.parse_json_object(result.text)
    except ValueError as exc:
        raise StatsError(f"could not read the question's parameters: {exc}") from exc
    return sanitize_params(raw), result


# --------------------------------------------------------------------------------------------
# Query building
# --------------------------------------------------------------------------------------------


@dataclass
class Query:
    prefix: str  # "WITH matched AS (...)", rendered with literal values
    topic_regex: str | None
    main: str  # the aggregate SELECT on `matched`
    doc_types: tuple[str, ...]
    outcomes: tuple[str, ...]
    min_paragraphs: int = TOPIC_MIN_PARAGRAPHS
    topic_articles: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)


def _topic_regex(params: dict) -> str | None:
    words = list(TOPICS[params["topic"]]["keywords"]) if params["topic"] else []
    words += params["keywords"]
    return "[[:<:]](" + "|".join(words) + ")" if words else None


def build_query(conn, params: dict) -> Query:
    group_by = params["group_by"]
    doc_types = tuple(params["doc_types"]) or DEFAULT_DOC_TYPES
    outcomes = tuple(params["outcomes"])
    if group_by == "reason" and not outcomes:
        outcomes = (
            "inadmissible",
        )  # whole-application inadmissibility; partly is reported separately
    conds: list[str] = []
    args: list = []

    def in_list(column: str, values: tuple[str, ...]) -> str:
        args.extend(values)
        return f"{column} IN ({', '.join(['%s'] * len(values))})"

    conds.append(in_list("d.doc_type", doc_types))
    if outcomes:
        conds.append(in_list("d.outcome", outcomes))
    if params["articles"]:
        arts = params["articles"]
        args.extend(arts + arts)
        marks = ", ".join(["%s"] * len(arts))
        conds.append(
            "EXISTS (SELECT 1 FROM unnest(d.articles) AS a "
            f"WHERE a IN ({marks}) OR split_part(a, '-', 1) IN ({marks}))"
        )
    if params["chambers"]:
        conds.append(in_list("d.chamber", tuple(params["chambers"])))
    if params["grounds"]:
        args.append(list(params["grounds"]))
        conds.append("d.inadmissibility_grounds && %s::text[]")
    if params["date_from"]:
        args.append(params["date_from"])
        conds.append("d.date >= %s")
    if params["date_to"]:
        args.append(params["date_to"])
        conds.append("d.date <= %s")
    regex = _topic_regex(params)
    topic = TOPICS.get(params["topic"]) if params["topic"] else None
    min_paragraphs = topic["min_paragraphs"] if topic else TOPIC_MIN_PARAGRAPHS
    topic_articles: tuple[str, ...] = tuple(topic["articles"]) if topic else ()
    if topic_articles:
        args.extend([*topic_articles, *topic_articles])
        marks = ", ".join(["%s"] * len(topic_articles))
        conds.append(
            "EXISTS (SELECT 1 FROM unnest(d.articles) AS a "
            f"WHERE split_part(a, '-', 1) IN ({marks}) OR a IN ({marks}))"
        )
    if regex:
        args.extend([regex, min_paragraphs])
        conds.append(
            "(SELECT count(*) FROM paragraphs p WHERE p.doc_id = d.item_id AND p.text ~* %s) >= %s"
        )

    where = "\n    AND ".join(conds)
    prefix_template = (
        "WITH matched AS (\n"
        "  SELECT d.item_id, d.case_name, d.date, d.doc_type, d.outcome, d.articles,"
        " d.inadmissibility_grounds\n"
        "  FROM documents d\n"
        f"  WHERE {where}\n"
        ")"
    )
    prefix = _render(conn, prefix_template, args)
    mains = {
        "none": "SELECT count(*) AS documents FROM matched",
        "reason": (
            "SELECT COALESCE(g, '(not stated)') AS reason, count(*) AS documents\n"
            "FROM matched LEFT JOIN LATERAL unnest(inadmissibility_grounds) AS g ON true\n"
            f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {ROWS_MAX}"
        ),
        "article": (
            "SELECT CASE WHEN a ~ '^P' THEN a ELSE split_part(a, '-', 1) END AS article,"
            " count(DISTINCT item_id) AS documents\n"
            "FROM matched CROSS JOIN LATERAL unnest(articles) AS a\n"
            f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {ROWS_MAX}"
        ),
        "outcome": (
            f"SELECT outcome, count(*) AS documents FROM matched GROUP BY 1 ORDER BY 2 DESC, 1"
            f" LIMIT {ROWS_MAX}"
        ),
        "doc_type": (
            f"SELECT doc_type, count(*) AS documents FROM matched GROUP BY 1 ORDER BY 2 DESC, 1"
            f" LIMIT {ROWS_MAX}"
        ),
        "year": (
            "SELECT date_part('year', date)::int AS year, count(*) AS documents FROM matched\n"
            f"GROUP BY 1 ORDER BY 1 DESC LIMIT {ROWS_MAX}"
        ),
    }
    return Query(
        prefix, regex, mains[group_by], doc_types, outcomes, min_paragraphs, topic_articles
    )


def _render(conn, template: str, args: list) -> str:
    """Fill %s placeholders with safely quoted literals, so the SQL we show is the SQL we run."""
    return psycopg.ClientCursor(conn).mogrify(template, args)


# --------------------------------------------------------------------------------------------
# Result assembly
# --------------------------------------------------------------------------------------------


def _cell(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, bool) or value is None or isinstance(value, int | float):
        return value
    return str(value)[:CELL_MAX_CHARS]


DOC_TYPE_NOUNS = {
    "judgment": ("judgment", "judgments"),
    "decision": ("admissibility decision", "admissibility decisions"),
    "communicated": ("communicated case", "communicated cases"),
    "legal_summary": ("legal summary", "legal summaries"),
    "legislation": ("legislation item", "legislation items"),
}
# What an outcome filter means, as a verb phrase for "UK judgments that ..."
OUTCOME_PHRASES = {
    "violation": "found a violation",
    "no_violation": "found no violation",
    "mixed": "found both a violation and a no-violation finding",
    "inadmissible": "were declared inadmissible",
    "partly_inadmissible": "were declared partly inadmissible",
    "struck_out": "were struck out",
    "admissible": "were declared admissible",
    "other": "had another outcome",
    "not_applicable": "have no outcome",
}
# What a ground filter means, after "declared inadmissible for ..."
GROUND_REASONS = {
    "manifestly_ill_founded": "being manifestly ill-founded",
    "non_exhaustion": "non-exhaustion of domestic remedies",
    "out_of_time": "being out of time (six-month rule)",
    "incompatible_ratione_materiae": "being outside the Convention's subject matter",
    "incompatible_ratione_personae": "being outside the Convention as to persons",
    "incompatible_ratione_temporis": "being outside the Convention as to time",
    "incompatible_ratione_loci": "being outside the Convention as to territory",
    "abuse_of_right": "abuse of the right of application",
    "no_significant_disadvantage": "no significant disadvantage",
    "substantially_same": "being substantially the same as an earlier application",
    "not_a_victim": "the applicant not being a victim",
    "other": "another stated ground",
}


def _or_join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def _outcome_clause(outcomes: tuple[str, ...]) -> str:
    chosen = set(outcomes)
    if chosen == {"violation", "mixed"}:
        return "found at least one violation"
    if chosen == {"inadmissible", "partly_inadmissible"}:
        return "were declared inadmissible in whole or in part"
    return _or_join([OUTCOME_PHRASES.get(o, o.replace("_", " ")) for o in outcomes])


def _outcome_verbs(outcomes: tuple[str, ...], plural: bool = True) -> str:
    verbs = _outcome_clause(outcomes)
    return verbs if plural else verbs.replace("were ", "was ").replace("have ", "has ")


def _scope_phrase(
    params: dict, query: Query, plural: bool = True, with_outcome: bool = True
) -> str:
    """The set being counted, in plain words; every filter in the SQL appears here.

    No "UK": every document in the corpus is a UK case, so the SQL never filters on the respondent State, and the
    sentence must not read as if it did (the Ask page and the explanation say what the corpus holds)."""
    if query.doc_types == DEFAULT_DOC_TYPES:
        nouns = "judgments and decisions" if plural else "judgment or decision"
    else:
        names = [DOC_TYPE_NOUNS[t][1 if plural else 0] for t in query.doc_types]
        nouns = _or_join(names) if len(names) > 1 else names[0]
    if params[
        "chambers"
    ]:  # "Grand Chamber judgments"; what the chamber field means is in the explanation
        nouns = f"{' or '.join(params['chambers'])} {nouns}"
    parts = [nouns]
    if params["topic"] or params["keywords"]:
        words = [TOPICS[params["topic"]]["label"]] if params["topic"] else []
        words += params["keywords"]
        parts.append("about " + " / ".join(words))
    if params["articles"]:
        parts.append("raising Article " + "/".join(params["articles"]))
    if params["date_from"] and params["date_to"]:
        parts.append(f"dated between {params['date_from']} and {params['date_to']}")
    elif params["date_from"]:
        parts.append(f"dated on or after {params['date_from']}")
    elif params["date_to"]:
        parts.append(f"dated on or before {params['date_to']}")
    clause = ""
    if query.outcomes and with_outcome:
        clause = "that " + _outcome_verbs(query.outcomes, plural)
    if params["grounds"]:
        reasons = _or_join([GROUND_REASONS.get(g, g.replace("_", " ")) for g in params["grounds"]])
        if not clause:
            clause = (
                "that were declared inadmissible" if plural else "that was declared inadmissible"
            )
        clause += f" for {reasons}"
    if clause:
        parts.append(clause)
    return " ".join(parts)


def _total_and_subset_sentence(
    params: dict, query: Query, scope_query: Query, total: int, count: int
) -> str:
    """'The indexed corpus has 10 Grand Chamber judgments; 9 of them found at least one violation.'"""
    scope = _scope_phrase(params, scope_query, plural=total != 1)
    plural_verbs = _outcome_verbs(query.outcomes)
    singular_verbs = _outcome_verbs(query.outcomes, plural=False)
    if total == 0:
        return f"The indexed corpus has no {_scope_phrase(params, scope_query)}."
    if total == 1:
        if count == 1:
            return f"The indexed corpus has 1 {scope}, and it {singular_verbs}."
        return f"The indexed corpus has 1 {scope}; it is not one that {singular_verbs}."
    if count == 0:
        return f"The indexed corpus has {total} {scope}; none of them {singular_verbs}."
    if count == total:
        return f"The indexed corpus has {total} {scope}; all {total} {plural_verbs}."
    verbs = singular_verbs if count == 1 else plural_verbs
    return f"The indexed corpus has {total} {scope}; {count} of them {verbs}."


def _explain(
    params: dict,
    query: Query,
    count: int,
    total: int,
    shown: int,
    rows,
    *,
    partly_extra: int = 0,
    scope_total: int | None = None,
    scope_query: Query | None = None,
    quoted: int = 0,
) -> str:
    """Plain-English definitions first (they decide what the number means), then caveats."""
    scope = _scope_phrase(params, query)
    if scope_total is not None and scope_query is not None:
        out = [
            f"Counted {scope_total} matching {_scope_phrase(params, scope_query)} in the indexed corpus, and "
            f"{count} of them {_outcome_verbs(query.outcomes, plural=count != 1)}: the same SQL template, run once "
            "without the "
            "outcome filter and once with it."
        ]
    elif params["count_of"] == "top_group" and count != total:
        out = [f"{count} of the {total} matching {scope} rest on the most common group."]
    else:
        out = [f"Counted {count} matching {scope} in the indexed corpus."]
    out.append(
        "Every document in the corpus is a UK case, so the SQL has no filter on the respondent State."
    )
    if query.outcomes == ("inadmissible",):
        out.append(
            "'Declared inadmissible' means the whole application was declared inadmissible"
            + (
                f"; {partly_extra} further matching decision(s) were only partly inadmissible and are not counted."
                if partly_extra
                else "."
            )
        )
    if {"violation", "mixed"} <= set(query.outcomes):
        out.append(
            "'At least one violation' = outcome violation (only violations) or mixed (at least one "
            "violation and at least one no-violation finding)."
        )
    if params["chambers"]:
        out.append(
            "'Grand Chamber', 'Chamber' and 'Committee' come from HUDOC's chamber field: the formation of "
            "judges that decided the case."
        )
    regex = query.topic_regex
    if regex:
        words = ", ".join(regex[len("[[:<:]](") : -1].split("|"))
        if query.topic_articles:
            arts = ", ".join(a.replace("5-1-f", "5(1)(f)") for a in query.topic_articles)
            out.append(
                f"HUDOC has no topic field, so 'deportation' is defined as: the document raises "
                f"Article {arts} and at least {query.min_paragraphs} of its paragraphs contain a word "
                f"starting {words} (see the SQL). Cases that merely use these words without such a "
                "complaint are excluded."
            )
        else:
            out.append(
                f"HUDOC has no topic field, so the topic is a text match: at least "
                f"{query.min_paragraphs} paragraphs contain a word starting {words}."
            )
    if params["group_by"] == "reason":
        missing = next((r[1] for r in rows if r[0] == "(not stated)"), 0)
        out.append(
            "Grounds come from HUDOC's conclusion where it names one, otherwise from the decision "
            "text; a decision can have several, so rows can add up to more than the total."
        )
        if missing:
            out.append(f"{missing} matching document(s) have no ground recorded.")
    elif params["group_by"] == "article":
        out.append(
            "A document can raise several Articles, so rows can add up to more than the total."
        )
    out.append(
        f"{shown} of {count} matching cases are listed as examples."
        if count > shown
        else f"All {shown} matching cases are listed as examples."
    )
    if shown:
        out.append(
            "The examples only illustrate the matching cases; the count itself comes from the SQL."
        )
    if shown and quoted < shown:
        out.append(
            f"{shown - quoted} example(s) are listed without a quote, because no paragraph of that case states "
            "the counted outcome."
        )
    return one_line(" ".join(out))[:EXPLANATION_MAX_CHARS]


@dataclass
class StatsRun:
    result: dict  # StatsQueryResult
    params: dict
    answer_text: str
    claims: list[dict]
    steps: list[dict]


_FINDING = r"(?:violations?|breach(?:es)?)\s+of\b"
_THERE_BE = r"(?<!whether )\bthere\s+(?:has\s+been|have\s+been|had\s+been|would\s+be|will\s+be|was|were|is)\s+"
# An operative clause that states a violation ("Holds that there has been a violation of Article 3"). Clauses that
# only reject a preliminary objection, join an issue to the merits, rule on admissibility, award just satisfaction
# or state no violation do not match.
VIOLATION_CLAUSE = re.compile(
    _THERE_BE + r"(?:an?\s+)?" + _FINDING + r"|\b(?:has|have)\s+been\s+violated\b", re.I
)
NO_VIOLATION_CLAUSE = re.compile(
    _THERE_BE + r"no\s+" + _FINDING + r"|\b(?:has|have)\s+not\s+been\s+violated\b", re.I
)
OPERATIVE_SECTION = "Operative provisions"


def _clause_kind(doc_outcome: str, filter_outcomes: tuple[str, ...]) -> str | None:
    """Which operative clause honestly illustrates this case under the outcome filter, if the filter is about one."""
    wanted = set(filter_outcomes)
    if doc_outcome in ("violation", "mixed") and wanted & {"violation", "mixed"}:
        return "violation"  # a mixed case is quoted by its violation clause, never its no-violation clause
    if doc_outcome == "no_violation" and "no_violation" in wanted:
        return "no_violation"
    return None


def pick_operative_clause(
    paragraphs: list[tuple[str, str]], kind: str, articles: list[str] | tuple[str, ...] = ()
) -> tuple[str, str] | None:
    """(paragraph id, text) of the first operative clause stating `kind` ("violation" / "no_violation"), preferring
    one that names a requested Article; None when no clause states it."""
    pattern = VIOLATION_CLAUSE if kind == "violation" else NO_VIOLATION_CLAUSE

    def names_article(text: str) -> bool:
        return any(
            re.search(rf"\bArticle\s+{re.escape(a.split('-')[0])}\b", text) for a in articles
        )

    honest = [(pid, text) for pid, text in paragraphs if pattern.search(text)]
    if not honest:
        return None
    return next(((pid, t) for pid, t in honest if names_article(t)), honest[0])


def _matching_cases(
    conn,
    query: Query,
    question: str,
    only_ground: str | None = None,
    articles: list[str] | None = None,
) -> list[dict]:
    """Up to CASES_MAX matched documents (MatchingCase dicts), each with the one paragraph that best shows why it
    matched. When the count is about violations (or no violations), the quote is an operative clause stating that
    outcome; a case with no such clause is listed without a quote rather than with a contradictory one."""
    hint = (
        query.topic_regex[len("[[:<:]](") : -1].replace("|", " ") if query.topic_regex else question
    )
    where = (
        _render(conn, "WHERE %s = ANY(inadmissibility_grounds)", [only_ground])
        if only_ground
        else ""
    )
    _, cases = execute_readonly(
        conn,
        f"{query.prefix}\nSELECT item_id, case_name, doc_type, outcome FROM matched {where} "
        f"ORDER BY date DESC, item_id LIMIT {CASES_MAX}",
    )
    if not cases:
        return []
    kinds = {doc_id: _clause_kind(outcome, query.outcomes) for doc_id, _, _, outcome in cases}
    chosen: dict[str, tuple[str, str] | None] = {}

    clause_docs = [d for d, k in kinds.items() if k]
    if clause_docs:
        marks = ", ".join(["%s"] * len(clause_docs))
        _, ops = execute_readonly(
            conn,
            _render(
                conn,
                f"SELECT p.id, p.doc_id, p.text FROM paragraphs p WHERE p.doc_id IN ({marks}) "
                "AND p.section = %s ORDER BY p.doc_id, p.position",
                [*clause_docs, OPERATIVE_SECTION],
            ),
        )
        by_doc: dict[str, list[tuple[str, str]]] = {}
        for pid, doc_id, text in ops:
            by_doc.setdefault(doc_id, []).append((pid, text))
        for doc_id in clause_docs:
            chosen[doc_id] = pick_operative_clause(
                by_doc.get(doc_id, []), kinds[doc_id], articles or ()
            )

    other_docs = [d for d, k in kinds.items() if not k]
    if other_docs:
        marks = ", ".join(["%s"] * len(other_docs))
        rank_parts, args = [], list(other_docs)
        if query.topic_regex:
            rank_parts.append(
                "WHEN p.text ~* %s AND p.text ~* 'inadmissible|rejected|ill-founded' THEN 0"
            )
            rank_parts.append("WHEN p.text ~* %s THEN 1")
            args += [query.topic_regex, query.topic_regex]
            density = "(length(p.text) - length(regexp_replace(p.text, %s, '', 'gi'))) DESC, "
            args_tail = [query.topic_regex]
        else:
            density, args_tail = "", []
        rank_parts.append(f"WHEN p.section = '{OPERATIVE_SECTION}' THEN 2")
        sql = _render(
            conn,
            "SELECT DISTINCT ON (p.doc_id) p.id, p.doc_id, p.text FROM paragraphs p "
            f"WHERE p.doc_id IN ({marks}) "
            f"ORDER BY p.doc_id, CASE {' '.join(rank_parts)} ELSE 3 END, {density}p.position",
            args + args_tail,
        )
        _, paras = execute_readonly(conn, sql)
        for pid, doc_id, text in paras:
            chosen[doc_id] = (pid, text)

    out = []
    for doc_id, case_name, doc_type, _ in cases:
        picked = chosen.get(doc_id)
        if picked is None and not kinds[doc_id]:
            continue  # no paragraphs at all (not a real document)
        pid, text = picked if picked else (None, "")
        out.append(
            {
                "doc_id": doc_id,
                "case_name": case_name[:120],
                "doc_type": doc_type,
                "paragraph_id": pid,
                "quote": cit.best_quote(text, "violation " + hint if kinds[doc_id] else hint)
                if pid
                else "",
                "link_target": cit.link_target(pid) if pid else f"/case/{doc_id}",
            }
        )
    return out


def _compose(
    params: dict,
    query: Query,
    count: int,
    total: int,
    top: tuple | None,
    rows,
    cases,
    *,
    scope_total: int | None = None,
    scope_query: Query | None = None,
) -> tuple[str, list[dict]]:
    """The answer sentences and their claims. A claim's evidence is the SQL shown, so it cites no paragraph: the
    examples after it illustrate matching cases and do not prove the count."""
    scope = _scope_phrase(params, query)
    group = params["group_by"]
    sql_reason = "The count comes straight from the SQL shown, not from a model."
    if top is not None:
        noun = "ground" if group == "reason" else group.replace("_", " ")
        shown = GROUND_LABELS.get(top[0], top[0]) if group == "reason" else str(top[0])
        first = f"The most common {noun} is {shown}: {count} of the {total} matching {scope}."
        claims = [(first, sql_reason)]
        sentences = [first]
    else:
        if scope_total is not None and scope_query is not None:
            first = _total_and_subset_sentence(params, query, scope_query, scope_total, count)
        else:
            scope = _scope_phrase(params, query, plural=count != 1)
            first = f"The indexed corpus has {count} {scope}."
        sentences = [first]
        claims = [(first, sql_reason)]
        if group != "none" and rows:
            if group == "reason":
                label = lambda v: GROUND_LABELS.get(v, v)  # noqa: E731
                noun = "Most common reasons"
            else:
                label = lambda v: str(v)  # noqa: E731
                noun = f"Breakdown by {group.replace('_', ' ')}"
            listing = "; ".join(f"{label(r[0])} ({r[1]})" for r in rows[:5])
            sentences.append(f"{noun}: {listing}.")
            claims.append((f"{noun}: {listing}.", "Computed by the SQL shown, not by a model."))
    text = " ".join(sentences)
    quoted = [c for c in cases if c["paragraph_id"]]
    if quoted:
        text += " Examples: " + " ".join(
            cit.marker(c["case_name"], c["paragraph_id"]) for c in quoted[:3]
        )
    out_claims = [
        {
            "id": f"c{i + 1}",
            "text": claim_text[:300],
            "citation_ids": [],
            "status": "supported",
            "reason": reason,
        }
        for i, (claim_text, reason) in enumerate(claims)
    ]
    return text, out_claims


def _top_group(params: dict, rows: list[list]) -> tuple | None:
    """For count_of = top_group: the biggest real group (never the '(not stated)' bucket)."""
    if params["count_of"] != "top_group" or params["group_by"] not in (
        "reason",
        "article",
        "outcome",
        "doc_type",
    ):
        return None
    return next((tuple(r) for r in rows if r and r[0] != "(not stated)"), None)


_TOTAL_AND_SUBSET = re.compile(
    r"\bhow many\b.+?(?:\band\b|,)\s*(?:then\s+)?(?:how many|what (?:share|proportion|number|percentage))\b",
    re.IGNORECASE | re.DOTALL,
)


def wants_total_and_subset(params: dict, question: str) -> bool:
    """'How many Grand Chamber judgments are there, and how many of them found a violation?': the question asks for
    the total of a scope AND how many of those have an outcome, so both numbers must be reported."""
    if not params["outcomes"] or params["count_of"] == "top_group":
        return False
    return params["count_of"] == "total_and_subset" or bool(_TOTAL_AND_SUBSET.search(question))


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def run_stats_full(conn, question: str, request_id: str) -> StatsRun:
    steps: list[dict] = []
    started = time.perf_counter()
    params, llm_result = extract_params(conn, question, request_id)
    steps.append(
        {
            "step": "generate",
            "model": llm_result.model,
            "tokens_in": llm_result.tokens_in,
            "tokens_out": llm_result.tokens_out,
            "tokens_cached": llm_result.tokens_cached,
            "cost_usd": llm_result.cost_usd,
            "latency_ms": (time.perf_counter() - started) * 1000,
        }
    )
    started = time.perf_counter()
    query = build_query(conn, params)
    _, count_rows = execute_readonly(conn, f"{query.prefix}\nSELECT count(*) FROM matched")
    total = int(count_rows[0][0])
    columns, raw_rows = execute_readonly(conn, f"{query.prefix}\n{query.main}")
    rows = [[_cell(v) for v in r] for r in raw_rows][:ROWS_MAX]
    top = _top_group(params, rows)
    count = int(top[1]) if top else total  # the graded number: documents in the top group, or all
    partly_extra = 0
    if query.outcomes == ("inadmissible",):
        other = build_query(conn, {**params, "outcomes": ["partly_inadmissible"]})
        _, extra = execute_readonly(conn, f"{other.prefix}\nSELECT count(*) FROM matched")
        partly_extra = int(extra[0][0])
    # "How many X, and how many of them Y": the same template once more, without the outcome filter
    scope_query: Query | None = None
    scope_total: int | None = None
    if wants_total_and_subset(params, question):
        scope_query = build_query(
            conn, {**params, "outcomes": [], "group_by": "none", "count_of": "total"}
        )
        _, scope_rows = execute_readonly(
            conn, f"{scope_query.prefix}\nSELECT count(*) AS documents FROM matched"
        )
        scope_total = int(scope_rows[0][0])
        if params["group_by"] == "none":
            columns = ["set", "documents"]
            rows = [
                [_cell(_cap(_scope_phrase(params, scope_query))), scope_total],
                [_cell(_cap(_outcome_verbs(query.outcomes))), count],
            ]
    only_ground = top[0] if top and params["group_by"] == "reason" and top[0] in GROUNDS else None
    cases = _matching_cases(conn, query, question, only_ground, params["articles"])
    steps.append(local_step("retrieve", None, (time.perf_counter() - started) * 1000))

    note = (
        "-- also run on the same `matched` set: SELECT count(*) FROM matched;"
        f" and the {CASES_MAX} most recent items, each with an example paragraph"
    )
    main_sql = f"{query.prefix}\n{query.main}"
    if scope_query is not None:
        main_sql = (
            "-- 1) the total, without the outcome filter\n"
            f"{scope_query.prefix}\nSELECT count(*) AS documents FROM matched;\n"
            "-- 2) how many of those have the outcome\n"
            f"{main_sql}"
        )
    shown_sql = f"{main_sql};\n{note}"
    if len(shown_sql) > SQL_MAX_CHARS:
        shown_sql = main_sql[:SQL_MAX_CHARS]
    answer_text, claims = _compose(
        params,
        query,
        count,
        total,
        top,
        rows,
        cases,
        scope_total=scope_total,
        scope_query=scope_query,
    )
    result = {
        "question": question[:500],
        "sql": shown_sql,
        "columns": columns[:6],
        "rows": [r[:6] for r in rows],
        "matching_cases": cases,
        "count": count,
        "scope_total": scope_total,
        "explanation": _explain(
            params,
            query,
            count,
            total,
            len(cases),
            rows,
            partly_extra=partly_extra,
            scope_total=scope_total,
            scope_query=scope_query,
            quoted=sum(1 for c in cases if c["paragraph_id"]),
        ),
    }
    return StatsRun(result, params, answer_text, claims, steps)


def run_stats(conn, question: str, request_id: str) -> dict:
    """-> StatsQueryResult dict."""
    return run_stats_full(conn, question, request_id).result
