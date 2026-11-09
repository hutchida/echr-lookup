# ruff: noqa: E501
"""Value questions ("Should the UK ...?", "Is the Human Rights Act good for the UK?").

These ask for a verdict, which the system never gives. They still deserve a real answer: what the
Court decided and why, the strongest sourced point on each side, and the relevant legislation. The
question's own words ("should", "good") retrieve poorly, though, so a small model first turns the
question into neutral search queries (the Court's reasoning, the State's side, the individual's
side, the legislation), and each is searched in addition to the original.
"""

from __future__ import annotations

import re
import time

from rag import config
from rag.answer import llm

VALUE_QUESTION = re.compile(
    r"\b(should|ought)\b"
    r"|\bis it (right|fair|wrong|good|bad|acceptable|justified|reasonable|ok|okay)\b"
    r"|\bwas it (right|fair|wrong|justified|reasonable)\b"
    r"|\b(good|bad|better|worse) for\b"
    r"|\bdo you (think|believe)\b"
    r"|\bwould it be (better|right|wise|fair)\b"
    r"|\bis (the|a|an)\b[^?]{0,60}\b(good|bad|right|wrong|fair|unfair|justified)\b",
    re.IGNORECASE,
)

MAX_QUERIES = 5

PLAN_SYSTEM = """You help a research tool that answers questions neutrally from European Court of Human Rights \
judgments, admissibility decisions, the Convention and the UK Human Rights Act 1998. The user's question asks \
for a verdict or value judgment, which the tool will not give. Write 3 to 5 short, neutral SEARCH QUERIES (not \
questions to the user) that would find the sources needed to set out what the Court decided and the positions \
on each side. Cover, in this order:
1. what the Court held and its reasoning on the underlying legal issue (name the Convention article or the \
leading case if you know it);
2. the State's / Government's argument or interest, and the margin of appreciation, on that issue;
3. the applicant's argument, or dissenting / concurring opinions, on that issue;
4. (only if relevant) the specific legislation, covering BOTH what it empowers courts to do and what it leaves to \
Parliament. For the Human Rights Act use queries such as "Human Rights Act 1998 section 2 courts must take into \
account Strasbourg case-law", "section 3 interpret legislation compatibly with Convention rights", "section 4 \
declaration of incompatibility", "section 10 remedial order", "section 6 acts of public authorities unlawful"; for the \
Convention name the article (e.g. Article 46 binding force of judgments, Article 58 denunciation).
Use legal vocabulary the judgments use. No opinions. Reply with only JSON: {"queries": ["...", "..."]}"""


LEGAL_PLAN_SYSTEM = """You help a research tool that answers legal questions neutrally from European Court of Human \
Rights judgments, admissibility decisions, legal summaries, the Convention and the UK Human Rights Act 1998. \
The user's question asks what the law is or what the Court has done. Write 3 or 4 short SEARCH QUERIES (not \
questions to the user) that would find, in the Court's own reasoning, everything needed for a balanced, \
well-evidenced answer. Cover, in this order:
1. the legal test or principle the Court applies to the issue, with the Convention article(s) it falls under;
2. the circumstances in which the Court found a violation, or that the State's action would breach the Convention;
3. the circumstances in which the Court found no violation, rejected the complaint, or allowed the State's action;
4. any second Convention article or ground that this kind of issue commonly engages, and how the Court balances it \
against the State's interest.
Write each query in the vocabulary the Court's reasoning uses ("the Court reiterates", "the Court considers", \
"would amount to", "would not violate", "proportionate", "margin of appreciation"). Aim at the Court's reasoning and \
findings, not at the text of domestic legislation, unless the question is about a statute. Each query covers ONE \
point and is under 18 words. Be neutral; no opinions. Reply with only JSON: {"queries": ["...", "..."]}"""


def is_value_question(question: str) -> bool:
    return bool(VALUE_QUESTION.search(question))


def plan_queries(
    conn, question: str, request_id: str, *, value: bool = True
) -> tuple[list[str], dict]:
    """-> (extra search queries, a "route"-step dict for the planning call). Never raises: if the
    planner fails the answer simply uses the original question alone. `value=False` plans for an
    explain question (the legal test and the outcomes both ways) instead of a value question."""
    started = time.perf_counter()
    result = None
    queries: list[str] = []
    try:
        result = llm.complete(
            conn,
            model=config.router_model(),
            system=PLAN_SYSTEM if value else LEGAL_PLAN_SYSTEM,
            messages=[{"role": "user", "content": f"Question: {question}"}],
            purpose="route",
            fake_key="plan",
            request_id=request_id,
            max_tokens=300 if value else 500,
        )
        raw = llm.parse_json_object(result.text).get("queries") or []
        queries = [q.strip() for q in raw if isinstance(q, str) and 3 <= len(q.strip()) <= 300]
    except Exception:
        queries = []
    step = {
        "step": "route",
        "model": result.model if result else None,
        "tokens_in": result.tokens_in if result else 0,
        "tokens_out": result.tokens_out if result else 0,
        "tokens_cached": result.tokens_cached if result else 0,
        "cost_usd": result.cost_usd if result else 0.0,
        "latency_ms": (time.perf_counter() - started) * 1000,
    }
    return queries[:MAX_QUERIES], step
