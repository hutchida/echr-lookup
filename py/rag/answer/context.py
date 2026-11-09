# ruff: noqa: E501
"""Retrieval and context building for the RAG path.

`rag.search.search` returns *chunks*; the model should be shown (and may cite) individual
*paragraphs*, so we look the cited paragraphs up in the `paragraphs` table and label each one with
its id and case name.
"""

from __future__ import annotations

import importlib
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from rag import config

DEFAULT_MODE = "hybrid_rerank"
DEFAULT_CHUNKING = "recursive"
DEFAULT_K = 12
MAX_CONTEXT_PARAGRAPHS = 24
MAX_CONTEXT_PARAGRAPHS_VALUE = 30  # value questions draw on several searches
EXTRA_QUERY_K = 6
OPERATIVE_DOCS_MAX = 10  # how many retrieved cases also get their operative provisions
OPERATIVE_PER_DOC_MAX = 3
# Value questions ("Should ...?") keep the context exactly as it was before answer-first: their
# neutrality is judged by the eval, and they need many sections of one statute or treaty.
VALUE_OPERATIVE_DOCS_MAX = 8
VALUE_OPERATIVE_PER_DOC_MAX = 4
CONTEXT_PARAGRAPH_CHARS = 1400
PER_DOC_MAX = 4  # paragraphs per case before operative provisions: no one case crowds out the rest


@dataclass
class Source:
    id: str  # paragraph id, e.g. 001-57619§88
    doc_id: str
    case_name: str
    doc_type: str
    date: str
    outcome: str
    text: str  # full paragraph text


def search_request(question: str, options: dict) -> dict:
    return {
        "query": question,
        "mode": options.get("mode") or DEFAULT_MODE,
        "chunking": options.get("chunking") or DEFAULT_CHUNKING,
        "k": options.get("k") or DEFAULT_K,
    }


def fetch_sources(conn, paragraph_ids: list[str]) -> dict[str, Source]:
    if not paragraph_ids:
        return {}
    rows = conn.execute(
        """
        SELECT p.id, p.doc_id, d.case_name, d.doc_type, d.date::text, d.outcome, p.text
        FROM paragraphs p JOIN documents d ON d.item_id = p.doc_id
        WHERE p.id = ANY(%s)
        """,
        (paragraph_ids,),
    ).fetchall()
    return {r[0]: Source(*r) for r in rows}


def operative_sources(
    conn,
    doc_ids: list[str],
    have: set[str],
    *,
    per_doc_max: int = OPERATIVE_PER_DOC_MAX,
    outcomes_only: bool = True,
) -> list[Source]:
    """The 'Holds that there has been no violation of Article 8' paragraphs of the retrieved cases.

    Retrieval ranks paragraphs by topic, so it often misses the one paragraph that states the
    outcome. Adding it lets a claim like "the Court found no violation" cite a paragraph that says so.
    """
    if not doc_ids:
        return []
    rows = conn.execute(
        """
        SELECT p.id, p.doc_id, d.case_name, d.doc_type, d.date::text, d.outcome, p.text
        FROM paragraphs p JOIN documents d ON d.item_id = p.doc_id
        WHERE p.doc_id = ANY(%s) AND p.section = 'Operative provisions'
        ORDER BY p.doc_id, p.position
        """,
        (doc_ids,),
    ).fetchall()
    out: list[Source] = []
    per_doc: dict[str, int] = {}
    for row in rows:
        if row[0] in have or per_doc.get(row[1], 0) >= per_doc_max:
            continue
        if outcomes_only and not OUTCOME_WORDS.search(
            row[6]
        ):  # skip "Holds" / "that the State is to pay"
            continue
        per_doc[row[1]] = per_doc.get(row[1], 0) + 1
        out.append(Source(*row))
    return sorted(out, key=lambda s: doc_ids.index(s.doc_id))


STATUTE_QUOTE = re.compile(
    r"^\W*(?:sections?|rules?|paragraphs?|regulations?|schedule)\s+\d+[\w()]*"
    r"(?:\s*(?:and|,|to)\s*\d+[\w()]*)*\s+(?:of|to)\s+(?:the|this)\b[^.]{0,120}?"
    r"\b(?:act|acts|rules|regulations|order|code)\b",
    re.IGNORECASE,
)
OUTCOME_WORDS = re.compile(
    r"violat|inadmissib|admissib|struck|jurisdiction|necessary to examine|friendly settlement",
    re.IGNORECASE,
)


def quotes_statute(s: Source) -> bool:
    """A paragraph of a judgment or decision that just recites domestic legislation ("Section 3(5)(a)
    of the Immigration Act 1971 provides ...") rather than the Court's own reasoning."""
    return s.doc_type != "legislation" and bool(STATUTE_QUOTE.match(s.text.lstrip()))


def demote_statute_quotes(sources: list[Source]) -> list[Source]:
    """Stable reorder: recited domestic legislation goes after the Court's own paragraphs, so it
    only fills space the reasoning does not need (the reranker tends to lift it to the top)."""
    return [s for s in sources if not quotes_statute(s)] + [s for s in sources if quotes_statute(s)]


def diversify(sources: list[Source], cap: int, per_doc: int = PER_DOC_MAX) -> list[Source]:
    """Keep rank order but at most `per_doc` paragraphs from any one document, up to `cap` in total.

    A reranker (or a keyword search) tends to lift one document's near-duplicate paragraphs (the
    same statute quoted in five judgments, or five paragraphs of one case); this keeps the context
    spread over more cases so the model can see the Court's reasoning in several of them.
    """
    kept: list[Source] = []
    counts: dict[str, int] = {}
    for s in sources:
        if counts.get(s.doc_id, 0) >= per_doc:
            continue
        counts[s.doc_id] = counts.get(s.doc_id, 0) + 1
        kept.append(s)
        if len(kept) >= cap:
            break
    return kept


def _paragraph_ids(result: dict) -> list[str]:
    ids: list[str] = []
    for hit in result["hits"]:
        for pid in hit["paragraph_ids"]:
            if pid not in ids:
                ids.append(pid)
    return ids


def retrieve(
    conn,
    question: str,
    options: dict,
    *,
    embedder=None,
    reranker=None,
    extra_queries: Sequence[str] | Callable[[], Sequence[str]] = (),
    value_question: bool = False,
) -> tuple[list[Source], list[dict]]:
    """Run search, then load the cited paragraphs in rank order. -> (sources, retrieve/rerank steps)."""
    search = importlib.import_module("rag.search")
    request = search_request(question, options)
    # With RERANK_ENABLED=0 and no reranker, rag.search degrades hybrid_rerank to hybrid itself.
    if request["mode"] == "hybrid_rerank" and reranker is None and config.rerank_enabled():
        reranker = search.get_reranker()
    started = time.perf_counter()
    result = search.search(conn, request, embedder=embedder, reranker=reranker)
    wall_ms = (time.perf_counter() - started) * 1000

    lists = [_paragraph_ids(result)]
    cap = MAX_CONTEXT_PARAGRAPHS
    extra_started = time.perf_counter()
    waited = 0.0
    if callable(extra_queries):  # a planner that ran while the main search did
        wait_started = time.perf_counter()
        extra_queries = extra_queries()
        waited = (time.perf_counter() - wait_started) * 1000  # the planner's own step counts this
    for query in extra_queries:  # value questions: neutral reformulations, searched without rerank
        extra_request = {**request, "query": query, "k": EXTRA_QUERY_K}
        if extra_request["mode"] == "hybrid_rerank":
            extra_request["mode"] = "hybrid"
        lists.append(_paragraph_ids(search.search(conn, extra_request, embedder=embedder)))
        cap = MAX_CONTEXT_PARAGRAPHS_VALUE
    extra_ms = (time.perf_counter() - extra_started) * 1000 - waited
    ordered: list[str] = []
    for position in range(max(len(x) for x in lists)):  # round-robin, so every side is represented
        for ids in lists:
            if position < len(ids) and ids[position] not in ordered:
                ordered.append(ids[position])
    if value_question:
        by_id = fetch_sources(conn, ordered[:cap])
        sources = [by_id[pid] for pid in ordered[:cap] if pid in by_id]
        doc_order = list(dict.fromkeys(s.doc_id for s in sources))[:VALUE_OPERATIVE_DOCS_MAX]
        sources += operative_sources(
            conn,
            doc_order,
            {s.id for s in sources},
            per_doc_max=VALUE_OPERATIVE_PER_DOC_MAX,
            outcomes_only=False,
        )
    else:
        by_id = fetch_sources(conn, ordered)
        sources = diversify(
            demote_statute_quotes([by_id[pid] for pid in ordered if pid in by_id]), cap
        )
        doc_order = list(dict.fromkeys(s.doc_id for s in sources))[:OPERATIVE_DOCS_MAX]
        sources += operative_sources(conn, doc_order, {s.id for s in sources})

    timings = result.get("timings_ms") or {}
    rerank_ms = timings.get("rerank")
    steps = [local_step("retrieve", None, max(wall_ms - (rerank_ms or 0), 0.0) + extra_ms)]
    if rerank_ms is not None:
        steps.append(local_step("rerank", config.reranker_name(), rerank_ms))
    return sources, steps


def local_step(step: str, model: str | None, latency_ms: float) -> dict:
    return {
        "step": step,
        "model": model,
        "tokens_in": 0,
        "tokens_out": 0,
        "tokens_cached": 0,
        "cost_usd": 0.0,
        "latency_ms": latency_ms,
    }


def one_line(text: str, limit: int | None = None) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if limit is None or len(flat) <= limit else flat[:limit].rstrip() + " …"


def build_context(sources: list[Source]) -> str:
    """Header line `[<paragraph id>] <case> (<type>, <year>, outcome: <outcome>)`, then one text line."""
    blocks = []
    for s in sources:
        header = f"[{s.id}] {s.case_name} ({s.doc_type}, {s.date[:4]}, outcome: {s.outcome})"
        blocks.append(f"{header}\n{one_line(s.text, CONTEXT_PARAGRAPH_CHARS)}")
    return "\n\n".join(blocks)
