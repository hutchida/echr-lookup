"""The six tools: plain functions `tool(conn, args, ...) -> contract result dict`.

The MCP layer (server.py) validates arguments, times, logs and serialises; nothing here knows MCP.
No LLM is called anywhere in this package.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

from api.queries import _ARTICLE_KEY
from api.queries import get_case as load_case
from echr_mcp.common import (
    DOC_TYPE_LABELS,
    OUTCOME_LABELS,
    RESULT_MAX_BYTES,
    ToolError,
    cite,
    corpus_block,
    corpus_sentence,
    display_case_name,
    json_bytes,
    nearest_sentence_cut,
    unique_cites,
    with_text_fragment,
)
from echr_mcp.labels import load_unnumbered_labels, para_label, unnumbered_labels
from rag import config
from rag.answer import citations as cit
from rag.answer import context as answer_context
from rag.answer import stats
from rag.search import search as run_search

SEARCH_K = 30
SEARCH_DEFAULT_LIMIT = 8
QUOTE_MAX_CHARS = 600
OPERATIVE_SECTION = "Operative provisions"


def _not_in_corpus(conn, what: str) -> ToolError:
    return ToolError(f"No {what} in this corpus ({corpus_sentence(corpus_block(conn))}).")


# --------------------------------------------------------------------------------------------
# Fitting a result under the size limit
# --------------------------------------------------------------------------------------------


def _water_fill(lengths: list[int], budget: int) -> int:
    """The largest per-item cap `c` with sum(min(length, c)) <= budget (at least 1)."""
    lo, hi = 1, max(lengths, default=1)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if sum(min(n, mid) for n in lengths) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return lo


def shrink_to_fit(result: dict, slots: list[tuple[dict, str, int]], limit: int = RESULT_MAX_BYTES):
    """Cut texts until `result` serialises within `limit` bytes. Returns True if anything was cut.

    `slots` are (holder, key, priority): the lowest priority is cut first, every text in a group
    to the same length (short ones stay whole), at a sentence boundary where possible, ending in
    '…'. A holder with a "truncated" key gets it set to true when its text was cut."""
    if json_bytes(result) <= limit:
        return False
    originals = [(h, k, h[k], p) for h, k, p in slots]
    for priority in sorted({p for *_, p in originals}):
        group = [(h, k, text) for h, k, text, p in originals if p == priority]
        lengths = [len(text) for _, _, text in group]
        scale = 1.0
        for _ in range(12):
            excess = json_bytes(result) - limit
            if excess <= 0:
                return True
            budget = max(int((sum(lengths) - excess) * scale), len(group))
            cap = _water_fill(lengths, budget)
            for holder, key, text in group:
                cut = nearest_sentence_cut(text, cap)
                if cut != text:
                    holder[key] = cut
                    if "truncated" in holder:
                        holder["truncated"] = True
            if json_bytes(result) <= limit or cap <= 1:
                break
            scale *= 0.85
    return True


# --------------------------------------------------------------------------------------------
# search_case_law
# --------------------------------------------------------------------------------------------

_DOC_TYPE_PLURALS = {
    "judgment": "judgments",
    "decision": "decisions",
    "communicated": "communicated cases",
    "legal_summary": "legal summaries",
    "legislation": "legislation",
}


def filters_in_words(args: dict) -> str:
    parts: list[str] = []
    if args.get("article"):
        parts.append(f"Article {args['article']}")
    if args.get("doc_type"):
        parts.append(_DOC_TYPE_PLURALS[args["doc_type"]])
    if args.get("outcome"):
        parts.append("outcome: " + args["outcome"].replace("_", " "))
    lo, hi = args.get("year_from"), args.get("year_to")
    if lo and hi:
        parts.append(f"{lo}–{hi}")
    elif lo:
        parts.append(f"from {lo}")
    elif hi:
        parts.append(f"up to {hi}")
    return "; ".join(parts)


def _search_filters(args: dict) -> dict:
    filters: dict = {}
    if args.get("article"):
        filters["article"] = args["article"]
    if args.get("doc_type"):
        filters["doc_types"] = [args["doc_type"]]
    if args.get("outcome"):
        filters["outcomes"] = [args["outcome"]]
    if args.get("year_from"):
        filters["date_from"] = f"{args['year_from']}-01-01"
    if args.get("year_to"):
        filters["date_to"] = f"{args['year_to']}-12-31"
    return filters


def _cut_quote(text: str, query: str) -> str:
    """The paragraph's best passage for `query`: whole sentences, '…' marking a cut inside one."""
    text = text.strip()
    budget = QUOTE_MAX_CHARS
    for _ in range(2):
        quote = cit.best_quote(text, query, max_chars=budget)
        start = text.find(quote)
        if start < 0 or quote == text:
            return quote
        end = start + len(quote)
        spans = cit._sentence_spans(text)
        lead = "" if any(s == start for s, _ in spans) else "…"
        trail = "" if any(e == end for _, e in spans) else "…"
        if len(quote) + len(lead) + len(trail) <= QUOTE_MAX_CHARS:
            return f"{lead}{quote}{trail}"
        budget = QUOTE_MAX_CHARS - len(lead) - len(trail)
    return f"{lead}{quote}{trail}"[:QUOTE_MAX_CHARS]


def _best_paragraph(candidates: list[dict], query: str) -> dict:
    """Of a chunk's paragraphs, the one whose best quote covers the most distinctive query words
    (digits weigh most, then words found in only one candidate); ties go to the first."""
    if len(candidates) == 1:
        return candidates[0]
    wanted = cit._tokens(query)
    words = [cit._TOKEN.findall(c["text"].lower()) for c in candidates]
    covers = [{t for t in wanted if any(cit._matches(t, w) for w in ws)} for ws in words]
    weight = {
        t: 3 if t.isdigit() else (2 if sum(t in c for c in covers) == 1 else 1) for t in wanted
    }
    scores = []
    for c in candidates:
        quote_words = cit._TOKEN.findall(cit.best_quote(c["text"], query, QUOTE_MAX_CHARS).lower())
        scores.append(
            sum(weight[t] for t in wanted if any(cit._matches(t, w) for w in quote_words))
        )
    return candidates[max(range(len(candidates)), key=lambda i: (scores[i], -i))]


def search_case_law(conn, args: dict, *, embedder=None, reranker=None) -> dict:
    query = args["query"].strip()
    limit = args.get("limit") or SEARCH_DEFAULT_LIMIT
    filters = _search_filters(args)
    request = {**answer_context.search_request(query, {}), "k": SEARCH_K}
    if filters:
        request["filters"] = filters
    found = run_search(conn, request, embedder=embedder, reranker=reranker)

    chunk_paragraphs: list[list[str]] = [h["paragraph_ids"] for h in found["hits"]]
    wanted = list(dict.fromkeys(pid for ids in chunk_paragraphs for pid in ids))
    rows = (
        conn.execute(
            """
            SELECT p.id, p.doc_id, p.number, p.section, p.text, d.case_name, d.doc_type,
                   d.date::text, d.outcome, d.articles, d.source_url
            FROM paragraphs p JOIN documents d ON d.item_id = p.doc_id
            WHERE p.id = ANY(%s) AND d.data_source = %s
            """,
            (wanted, config.data_source()),
        ).fetchall()
        if wanted
        else []
    )
    names = [
        "id",
        "doc_id",
        "number",
        "section",
        "text",
        "case_name",
        "doc_type",
        "date",
        "outcome",
        "articles",
        "url",
    ]
    paragraphs = {r[0]: dict(zip(names, r, strict=True)) for r in rows}

    chosen: list[dict] = []
    used: set[str] = set()
    for ids in chunk_paragraphs:
        candidates = [paragraphs[i] for i in ids if i in paragraphs and i not in used]
        if not candidates:
            continue
        para = _best_paragraph(candidates, query)
        used.add(para["id"])
        chosen.append(para)
        if len(chosen) >= limit:
            break
    labels = load_unnumbered_labels(
        conn, [p["doc_id"] for p in chosen if p["number"] is None], config.data_source()
    )

    hits: list[dict] = []
    for para in chosen:
        label = para_label(para["id"], para["number"], labels)
        quote = _cut_quote(para["text"], query)
        hits.append(
            {
                "rank": len(hits) + 1,
                "paragraph_id": para["id"],
                "para_label": label,
                "doc_id": para["doc_id"],
                "case_name": display_case_name(para["case_name"]),
                "doc_type": para["doc_type"],
                "doc_type_label": DOC_TYPE_LABELS[para["doc_type"]],
                "date": para["date"],
                "outcome": para["outcome"],
                "articles": list(para["articles"])[:60],
                "section": para["section"],
                "quote": quote,
                "hudoc_url": with_text_fragment(para["url"], quote),
                "cite": cite(para["case_name"], para["doc_type"], label),
            }
        )
    unique_cites(hits)
    result = {
        "query": query,
        "filters": filters_in_words(args),
        "hits": hits,
        "corpus": corpus_block(conn),
    }
    while len(hits) > 1 and json_bytes(result) > RESULT_MAX_BYTES:
        hits.pop()
    return result


# --------------------------------------------------------------------------------------------
# get_paragraphs
# --------------------------------------------------------------------------------------------

_PARAGRAPH_SQL = """
SELECT p.id, p.doc_id, p.position, p.number, p.section, p.text, d.case_name, d.doc_type,
       d.source_url
FROM paragraphs p JOIN documents d ON d.item_id = p.doc_id
WHERE d.data_source = %s AND """


def _paragraph_dict(row: tuple, requested: bool, labels: dict[str, str]) -> dict:
    pid, doc_id, _position, number, section, text, case_name, doc_type, url = row
    label = para_label(pid, number, labels)
    return {
        "paragraph_id": pid,
        "para_label": label,
        "doc_id": doc_id,
        "case_name": display_case_name(case_name),
        "doc_type": doc_type,
        "doc_type_label": DOC_TYPE_LABELS[doc_type],
        "number": number,
        "section": section,
        "text": text,
        "truncated": False,
        "requested": requested,
        "hudoc_url": with_text_fragment(url, text),
        "cite": cite(case_name, doc_type, label),
    }


def get_paragraphs(conn, args: dict) -> dict:
    ids = list(dict.fromkeys(args["paragraph_ids"]))
    neighbours = args.get("neighbours") or 0
    source = config.data_source()
    found = {
        r[0]: r for r in conn.execute(_PARAGRAPH_SQL + "p.id = ANY(%s)", (source, ids)).fetchall()
    }
    not_found = [i[:64] for i in ids if i not in found]
    # per document, in the order the documents were first asked for: position -> (row, requested)
    docs: dict[str, dict[int, tuple[tuple, bool]]] = {}
    for pid in ids:
        if pid not in found:
            continue
        row = found[pid]
        doc, position = row[1], row[2]
        entries = docs.setdefault(doc, {})
        entries[position] = (row, True)
        if neighbours:
            for r in conn.execute(
                _PARAGRAPH_SQL + "p.doc_id = %s AND p.position BETWEEN %s AND %s",
                (source, doc, position - neighbours, position + neighbours),
            ).fetchall():
                entries.setdefault(r[2], (r, False))
    labels = load_unnumbered_labels(
        conn,
        [row[1] for entries in docs.values() for row, _ in entries.values() if row[3] is None],
        source,
    )
    paragraphs: list[dict] = []
    distance: dict[str, int] = {}
    requested_positions = {
        doc: sorted(p for p, (_, req) in entries.items() if req) for doc, entries in docs.items()
    }
    for doc, entries in docs.items():
        for position in sorted(entries):
            row, requested = entries[position]
            para = _paragraph_dict(row, requested, labels)
            paragraphs.append(para)
            distance[para["paragraph_id"]] = (
                0 if requested else min(abs(position - q) for q in requested_positions[doc])
            )
    unique_cites(paragraphs)
    result = {"paragraphs": paragraphs, "not_found": not_found, "corpus": corpus_block(conn)}
    slots = [(p, "text", 1 if p["requested"] else 0) for p in paragraphs]
    shrink_to_fit(result, slots)
    # Only when even one character per paragraph does not fit: drop the farthest neighbours.
    while json_bytes(result) > RESULT_MAX_BYTES:
        far = max(
            (p for p in paragraphs if not p["requested"]),
            key=lambda p: distance[p["paragraph_id"]],
            default=None,
        )
        if far is None:
            break
        paragraphs.remove(far)
    return result


# --------------------------------------------------------------------------------------------
# get_case
# --------------------------------------------------------------------------------------------

OUTLINE_MAX = 12
OPERATIVE_MAX = 30


def _outline(paragraphs: list[dict]) -> list[dict]:
    runs: list[dict] = []
    for p in paragraphs:
        if runs and runs[-1]["section"] == p["section"]:
            runs[-1]["last_paragraph_id"] = p["id"]
            runs[-1]["paragraph_count"] += 1
        else:
            runs.append(
                {
                    "section": p["section"],
                    "first_paragraph_id": p["id"],
                    "last_paragraph_id": p["id"],
                    "paragraph_count": 1,
                }
            )
    if len(runs) > OUTLINE_MAX:  # merge the tail into the last kept run
        keep, tail = runs[: OUTLINE_MAX - 1], runs[OUTLINE_MAX - 1 :]
        keep.append(
            {
                "section": tail[0]["section"],
                "first_paragraph_id": tail[0]["first_paragraph_id"],
                "last_paragraph_id": tail[-1]["last_paragraph_id"],
                "paragraph_count": sum(r["paragraph_count"] for r in tail),
            }
        )
        runs = keep
    return runs


def get_case(conn, args: dict) -> dict:
    case_id = args["case_id"]
    loaded = load_case(conn, case_id)
    doc = loaded["document"] if loaded else None
    if doc is None or doc["data_source"] != config.data_source():
        raise _not_in_corpus(conn, f"case {case_id}")
    paragraphs = loaded["paragraphs"]
    labels = unnumbered_labels(
        doc["doc_type"], [(p["id"], p["number"], p["section"], p["text"][:40]) for p in paragraphs]
    )
    operative = [
        {
            "paragraph_id": p["id"],
            "para_label": para_label(p["id"], p["number"], labels),
            "text": nearest_sentence_cut(p["text"], 1500),
            "cite": cite(
                doc["case_name"], doc["doc_type"], para_label(p["id"], p["number"], labels)
            ),
        }
        for p in paragraphs
        if p["section"] == OPERATIVE_SECTION
    ][:OPERATIVE_MAX]
    result = {
        "doc_id": doc["item_id"],
        "case_name": display_case_name(doc["case_name"]),
        "doc_type": doc["doc_type"],
        "doc_type_label": DOC_TYPE_LABELS[doc["doc_type"]],
        "date": doc["date"],
        "chamber": doc["chamber"],
        "application_numbers": list(doc["application_numbers"])[:20],
        "articles": list(doc["articles"])[:60],
        "importance": doc["importance"],
        "outcome": doc["outcome"],
        "outcome_label": OUTCOME_LABELS[doc["outcome"]],
        "outcome_raw": (doc["outcome_raw"] or None) and doc["outcome_raw"][:2000],
        "inadmissibility_grounds": doc["inadmissibility_grounds"],
        "hudoc_url": doc["source_url"],
        "paragraph_count": len(paragraphs),
        "operative_provisions": operative,
        "outline": _outline(paragraphs),
        "corpus": corpus_block(conn),
    }
    shrink_to_fit(result, [(o, "text", 0) for o in operative])
    return result


# --------------------------------------------------------------------------------------------
# count_cases
# --------------------------------------------------------------------------------------------

SQL_MAX_CHARS = 4000
CASES_MAX = 20
SQL_NOTE = (
    "-- also run on the same `matched` set: SELECT count(*) FROM matched; and the "
    f"{CASES_MAX} most recent matching cases"
)


def _definitions(params: dict, query, partly_extra: int) -> list[str]:
    out: list[str] = []
    outcomes = set(query.outcomes)
    if {"violation", "mixed"} <= outcomes:
        out.append(
            "'Found a violation' counts outcomes 'violation' (only violation findings) and "
            "'mixed' (at least one violation and at least one no-violation finding)."
        )
        outcomes -= {"violation", "mixed"}
    if query.outcomes == ("inadmissible",):
        out.append(
            "'Declared inadmissible' means the whole application was declared inadmissible; "
            + (
                f"{partly_extra} further matching decision(s) were only partly inadmissible and "
                "are not counted."
                if partly_extra
                else "partly inadmissible decisions are not counted."
            )
        )
        outcomes -= {"inadmissible"}
    for outcome in sorted(outcomes):
        out.append(f"Outcome '{outcome}': {OUTCOME_LABELS.get(outcome, outcome)}.")
    if params["doc_types"]:
        names = ", ".join(DOC_TYPE_LABELS[t].lower() for t in query.doc_types)
        out.append(f"Document types counted: {names}.")
    else:
        out.append(
            "Court documents only by default: judgments, decisions and communicated cases; "
            "legal summaries re-describe judgments and would double count."
        )
    if params["chambers"]:
        out.append(
            "Grand Chamber = the Court's 17-judge formation; 'Chamber' means the ordinary "
            "7-judge Chamber; 'Committee' = a three-judge formation. Taken from HUDOC's chamber "
            "field."
        )
    if query.topic_regex:
        words = ", ".join(query.topic_regex[len("[[:<:]](") : -1].split("|"))
        if query.topic_articles:
            arts = ", ".join(a.replace("5-1-f", "5(1)(f)") for a in query.topic_articles)
            out.append(
                "HUDOC has no topic field, so a 'deportation' case is one that raises Article "
                f"{arts} and has at least {query.min_paragraphs} paragraphs containing a word "
                f"starting {words}."
            )
        else:
            out.append(
                "HUDOC has no topic field, so the topic is a text match: at least "
                f"{query.min_paragraphs} paragraphs contain a word starting {words}."
            )
    if params["articles"]:
        out.append("An Article filter also matches its sub-paragraphs (Article 8 matches 8-1).")
    if params["group_by"] == "reason":
        out.append(
            "Grounds come from HUDOC's conclusion where it names one, otherwise from the decision "
            "text; a decision can rest on several grounds, so the rows can add up to more than "
            "the total."
        )
    elif params["group_by"] == "article":
        out.append(
            "A document can raise several Articles, so rows can add up to more than the total."
        )
    out.append(
        "Every document in the corpus is a UK case, so the SQL has no filter on the respondent "
        "State."
    )
    return [d[:400] for d in out[:10]]


def _matching_cases(conn, query, params: dict, top: tuple | None) -> list[dict]:
    where, args = "", []
    if top is not None:
        group, key = params["group_by"], top[0]
        if group == "reason" and key in stats.GROUNDS:
            where, args = "WHERE %s = ANY(m.inadmissibility_grounds)", [key]
        elif group == "outcome":
            where, args = "WHERE m.outcome = %s", [key]
        elif group == "doc_type":
            where, args = "WHERE m.doc_type = %s", [key]
        elif group == "article":
            where = (
                "WHERE EXISTS (SELECT 1 FROM unnest(m.articles) AS a WHERE "
                "CASE WHEN a ~ '^P' THEN a ELSE split_part(a, '-', 1) END = %s)"
            )
            args = [key]
    where = stats._render(conn, where, args) if where else ""
    _, rows = stats.execute_readonly(
        conn,
        f"{query.prefix}\nSELECT m.item_id, m.case_name, m.doc_type, m.date, m.outcome, "
        "d.source_url FROM matched m JOIN documents d ON d.item_id = m.item_id "
        f"{where} ORDER BY m.date DESC, m.item_id LIMIT {CASES_MAX}",
    )
    return [
        {
            "doc_id": doc_id,
            "case_name": display_case_name(case_name),
            "doc_type": doc_type,
            "doc_type_label": DOC_TYPE_LABELS[doc_type],
            "date": day.isoformat(),
            "outcome": outcome,
            "hudoc_url": url,
        }
        for doc_id, case_name, doc_type, day, outcome, url in rows
    ]


def count_cases(conn, args: dict) -> dict:
    """The same template the /ask stats path runs (rag.answer.stats), minus the model: the host
    fills the parameters, we validate them, build the SQL and run it read-only."""
    params = stats.sanitize_params(args)
    query = stats.build_query(conn, params)
    _, count_rows = stats.execute_readonly(conn, f"{query.prefix}\nSELECT count(*) FROM matched")
    total = int(count_rows[0][0])
    columns, raw_rows = stats.execute_readonly(conn, f"{query.prefix}\n{query.main}")
    rows = [[stats._cell(v) for v in r] for r in raw_rows][: stats.ROWS_MAX]
    top = stats._top_group(params, rows)
    count = int(top[1]) if top else total
    partly_extra = 0
    if query.outcomes == ("inadmissible",):
        other = stats.build_query(conn, {**params, "outcomes": ["partly_inadmissible"]})
        _, extra = stats.execute_readonly(conn, f"{other.prefix}\nSELECT count(*) FROM matched")
        partly_extra = int(extra[0][0])
    scope_query = None
    scope_total = None
    if stats.wants_total_and_subset(params, ""):
        scope_query = stats.build_query(
            conn, {**params, "outcomes": [], "group_by": "none", "count_of": "total"}
        )
        _, scope_rows = stats.execute_readonly(
            conn, f"{scope_query.prefix}\nSELECT count(*) AS documents FROM matched"
        )
        scope_total = int(scope_rows[0][0])
        if params["group_by"] == "none":
            columns = ["set", "documents"]
            rows = [
                [stats._cell(stats._cap(stats._scope_phrase(params, scope_query))), scope_total],
                [stats._cell(stats._cap(stats._outcome_verbs(query.outcomes))), count],
            ]
    cases = _matching_cases(conn, query, params, top)

    main_sql = f"{query.prefix}\n{query.main}"
    if scope_query is not None:
        main_sql = (
            "-- 1) the total, without the outcome filter\n"
            f"{scope_query.prefix}\nSELECT count(*) AS documents FROM matched;\n"
            "-- 2) how many of those have the outcome\n"
            f"{main_sql}"
        )
    sql = f"{main_sql};\n{SQL_NOTE}"
    if len(sql) > SQL_MAX_CHARS:
        cut_note = "\n-- (cut: the SQL is longer than 4000 characters)"
        sql = main_sql[: SQL_MAX_CHARS - len(cut_note)] + cut_note
    answer, _claims = stats._compose(
        params, query, count, total, top, rows, [], scope_total=scope_total, scope_query=scope_query
    )
    top_group = None
    if top is not None:
        label = (
            stats.GROUND_LABELS.get(top[0], str(top[0]))
            if params["group_by"] == "reason"
            else str(top[0])
        )
        top_group = {"key": str(top[0])[:60], "label": label[:120], "count": int(top[1])}
    return {
        "answer": answer[:1000],
        "count": count,
        "scope_total": scope_total,
        "top_group": top_group,
        "filters": stats._scope_phrase(params, query)[:600],
        "definitions": _definitions(params, query, partly_extra),
        "sql": sql,
        "columns": columns[:6],
        "rows": [r[:6] for r in rows],
        "matching_cases": cases,
        "params": params,
        "corpus": corpus_block(conn),
    }


# --------------------------------------------------------------------------------------------
# corpus_info
# --------------------------------------------------------------------------------------------

MISSING = (
    {
        "what": "Everything outside this sample",
        "count": None,
        "why": (
            "Snapshot mode: a small committed sample of UK documents chosen for the demo, not the "
            "full HUDOC download (about 3,500 UK documents)."
        ),
        "snapshot_only": True,
    },
    {
        "what": "Other states' cases",
        "count": None,
        "why": "Only cases against the United Kingdom were downloaded.",
    },
    {
        "what": "European Commission of Human Rights reports",
        "count": 307,
        "why": (
            "HUDOC lists them without a document type this system supports, so they were skipped "
            "(full download)."
        ),
    },
    {
        "what": "Scanned older decisions (1970s–2000s)",
        "count": 212,
        "why": (
            "HUDOC holds them as scanned images with no text to search or quote (full download)."
        ),
    },
    {
        "what": "Communicated cases without numbered paragraphs",
        "count": 45,
        "why": (
            "Their text has no paragraph numbers to cite, so they failed parsing (full download)."
        ),
    },
)


def corpus_info(conn, args: dict | None = None) -> dict:
    source = config.data_source()
    documents = conn.execute(
        "SELECT count(*) FROM documents WHERE data_source = %s", (source,)
    ).fetchone()[0]
    paragraphs = conn.execute(
        "SELECT count(*) FROM paragraphs p JOIN documents d ON d.item_id = p.doc_id "
        "WHERE d.data_source = %s",
        (source,),
    ).fetchone()[0]
    by_doc_type = [
        {"key": k, "label": DOC_TYPE_LABELS[k], "count": n}
        for k, n in conn.execute(
            "SELECT doc_type, count(*) FROM documents WHERE data_source = %s "
            "GROUP BY 1 ORDER BY 2 DESC, 1",
            (source,),
        ).fetchall()
    ]
    by_outcome = [
        {"key": k, "label": OUTCOME_LABELS[k], "count": n}
        for k, n in conn.execute(
            "SELECT outcome, count(*) FROM documents WHERE data_source = %s "
            "GROUP BY 1 ORDER BY 2 DESC, 1",
            (source,),
        ).fetchall()
    ]
    by_article = [
        {"key": k, "count": n}
        for k, n in conn.execute(
            "SELECT key, count(DISTINCT item_id) FROM "
            f"(SELECT item_id, {_ARTICLE_KEY} AS key FROM documents, unnest(articles) a "
            "WHERE data_source = %s) t WHERE key IS NOT NULL GROUP BY key "
            "ORDER BY 2 DESC, 1 LIMIT 25",
            (source,),
        ).fetchall()
    ]
    first, last = conn.execute(
        "SELECT min(extract(year FROM date))::int, max(extract(year FROM date))::int "
        "FROM documents WHERE data_source = %s",
        (source,),
    ).fetchone()
    missing = [
        {k: v for k, v in m.items() if k != "snapshot_only"}
        for m in MISSING
        if source == "snapshot" or not m.get("snapshot_only")
    ]
    return {
        "corpus": corpus_block(conn),
        "totals": {"documents": int(documents), "paragraphs": int(paragraphs)},
        "by_doc_type": by_doc_type,
        "by_outcome": by_outcome,
        "by_article": by_article,
        "year_range": {"from": first or 0, "to": last or 0},
        "missing": missing,
    }


# --------------------------------------------------------------------------------------------
# check_quote
# --------------------------------------------------------------------------------------------

_QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"', "”": '"', "„": '"'})
_DASHES = re.compile("[‐‑‒–—―−]")
_GAP = re.compile(r"\[\s*\.\.\.\s*\]|\.\.\.")


def normalise(text: str) -> str:
    """NFKC, curly quotes -> straight, dashes -> '-', whitespace runs -> one space. (NFKC also
    turns '…' into '...', which check_quote then reads as an omission.)"""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    return re.sub(r"\s+", " ", _DASHES.sub("-", text)).strip()


def _segments(quote: str) -> list[str]:
    return [s.strip() for s in _GAP.split(normalise(quote)) if s.strip()]


def is_verbatim(paragraph: str, quote: str) -> bool:
    text, segments = normalise(paragraph), _segments(quote)
    position = 0
    for segment in segments:
        found = text.find(segment, position)
        if found < 0:
            return False
        position = found + len(segment)
    return bool(segments)


def closest_window(paragraph: str, quote: str) -> tuple[str, float]:
    """The 1-3 consecutive sentences of `paragraph` most similar to `quote`, verbatim, and the
    similarity ratio (difflib) of that window's normalised text to the normalised quote."""
    target = " ".join(_segments(quote)) or normalise(quote)
    spans = cit._sentence_spans(paragraph)
    best, best_ratio = (0, len(paragraph)), -1.0
    for i in range(len(spans)):
        for j in range(i, min(i + 3, len(spans))):
            window = paragraph[spans[i][0] : spans[j][1]]
            matcher = difflib.SequenceMatcher(None, normalise(window), target, autojunk=False)
            ratio = matcher.ratio()
            if ratio > best_ratio:
                best, best_ratio = (spans[i][0], spans[j][1]), ratio
    text = paragraph[best[0] : best[1]].strip()
    if len(text) > QUOTE_MAX_CHARS:
        text = nearest_sentence_cut(text, QUOTE_MAX_CHARS)
    return text, max(best_ratio, 0.0)


def check_quote(conn, args: dict) -> dict:
    paragraph_id, quote = args["paragraph_id"], args["quote"]
    corpus = corpus_block(conn)
    row = conn.execute(
        _PARAGRAPH_SQL + "p.id = %s", (config.data_source(), paragraph_id)
    ).fetchone()
    if row is None:
        return {
            "paragraph_id": paragraph_id[:64],
            "paragraph_found": False,
            "verbatim": False,
            "closest_match": None,
            "similarity": 0,
            "para_label": None,
            "cite": None,
            "corpus": corpus,
        }
    paragraph = row[5]
    label = para_label(
        paragraph_id,
        row[3],
        load_unnumbered_labels(conn, [row[1]], config.data_source()) if row[3] is None else {},
    )
    verbatim = is_verbatim(paragraph, quote)
    closest, ratio = closest_window(paragraph, quote)
    return {
        "paragraph_id": paragraph_id[:64],
        "paragraph_found": True,
        "verbatim": verbatim,
        "closest_match": closest,
        "similarity": 1.0 if verbatim else round(min(ratio, 1.0), 4),
        "para_label": label,
        "cite": cite(row[6], row[7], label),
        "corpus": corpus,
    }
