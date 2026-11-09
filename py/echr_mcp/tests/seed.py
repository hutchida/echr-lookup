"""A small seeded corpus for the MCP tests: Chahal (real paragraphs 78-80 and operative provisions
from the contract fixtures) plus synthetic cases for counting. Fake embedder, no ML."""

from __future__ import annotations

from rag.contract import load_fixture
from rag.index import get_embedder, replace_chunks, reset, upsert_document

CHAHAL = "001-58004"
OTHMAN = "001-108629"
OTHMAN_SUMMARY = "002-44"
MCCANN = "001-57943"


def _doc(item_id: str, case_name: str, **over) -> dict:
    base = load_fixture("SourceDocument")
    return {
        **base,
        "item_id": item_id,
        "case_name": case_name,
        "source_url": f"https://hudoc.echr.coe.int/eng?i={item_id}",
        "sha256": item_id.encode().hex().ljust(64, "0")[:64],
        "data_source": "snapshot",
        **over,
    }


def _para(doc_id: str, ref: str, text: str, section: str = "The Law") -> dict:
    number = int(ref) if ref.isdigit() else None
    return {
        "id": f"{doc_id}§{ref}",
        "doc_id": doc_id,
        "number": number,
        "section": section,
        "text": text,
    }


def _filler(doc_id: str, numbers, section: str, topic: str) -> list[dict]:
    return [
        _para(
            doc_id,
            str(n),
            f"Paragraph {n} of the {section} section discusses {topic}. "
            f"It records submission number {n} made by the parties.",
            section,
        )
        for n in numbers
    ]


def chahal_paragraphs() -> list[dict]:
    fixture = load_fixture("McpGetParagraphsResult")
    real = {p["paragraph_id"].split("§")[1]: p["text"] for p in fixture["paragraphs"]}
    case = load_fixture("McpGetCaseResult")
    paras = _filler(CHAHAL, range(1, 12), "Procedure", "the procedure before the Commission")
    paras += _filler(CHAHAL, range(12, 72), "The Facts", "the facts of the deportation order")
    for n in range(72, 162):
        if str(n) in real:
            paras.append(_para(CHAHAL, str(n), real[str(n)], "The Law"))
        else:
            paras += _filler(CHAHAL, [n], "The Law", "national security and ill-treatment risk")
    paras += [
        _para(CHAHAL, o["paragraph_id"].split("§")[1], o["text"], "Operative provisions")
        for o in case["operative_provisions"]
    ]
    paras += [
        _para(CHAHAL, "u4", "Joint partly dissenting opinion of the judges.", "Other"),
        _para(CHAHAL, "u5", "Appendix: list of the applicants' representatives.", "Other"),
    ]
    return paras


def corpus() -> list[tuple[dict, list[dict]]]:
    """(document, paragraphs) pairs."""
    no_grounds = {"inadmissibility_grounds": None, "inadmissibility_grounds_source": None}
    chahal = _doc(
        CHAHAL,
        "CHAHAL v. THE UNITED KINGDOM",
        doc_type="judgment",
        chamber="Grand Chamber",
        date="1996-11-15",
        articles=["3", "5", "5-1", "5-1-f", "5-4", "8", "13"],
        outcome="mixed",
        outcome_raw="Violation of Art. 3;Violation of Art. 5-4;No violation of Art. 5-1",
        importance=2,
        application_numbers=["22414/93"],
        **no_grounds,
    )
    hits = {h["paragraph_id"]: h for h in load_fixture("McpSearchCaseLawResult")["hits"]}
    othman = _doc(
        OTHMAN,
        "OTHMAN (ABU QATADA) v. THE UNITED KINGDOM",
        doc_type="judgment",
        chamber="Chamber",
        date="2012-01-17",
        articles=["3", "5", "5-1", "6", "6-1", "13"],
        outcome="mixed",
        outcome_raw="Violation of Art. 6;No violation of Art. 3",
        importance=1,
        application_numbers=["8139/09"],
        **no_grounds,
    )
    othman_paras = _filler(OTHMAN, range(1, 25), "The Facts", "the applicant's background")
    othman_paras.append(_para(OTHMAN, "25", hits[f"{OTHMAN}§25"]["quote"], "The Facts"))
    othman_paras += _filler(OTHMAN, range(26, 185), "The Law", "assurances from Jordan")
    othman_paras.append(_para(OTHMAN, "185", hits[f"{OTHMAN}§185"]["quote"], "The Law"))
    summary = _doc(
        OTHMAN_SUMMARY,
        "OTHMAN (ABU QATADA) v. THE UNITED KINGDOM",
        doc_type="legal_summary",
        chamber=None,
        date="2012-01-17",
        articles=["3", "5", "6"],
        outcome="mixed",
        importance=None,
        application_numbers=[],
        **no_grounds,
    )
    summary_paras = [_para(OTHMAN_SUMMARY, "u3", hits[f"{OTHMAN_SUMMARY}§u3"]["quote"], "Other")]
    mccann = _doc(
        MCCANN,
        "McCANN AND OTHERS v. THE UNITED KINGDOM",
        doc_type="judgment",
        chamber="Grand Chamber",
        date="1995-09-27",
        articles=["2"],
        outcome="violation",
        importance=1,
        application_numbers=["18984/91"],
        **no_grounds,
    )
    mccann_paras = _filler(MCCANN, range(1, 6), "The Law", "the use of lethal force")
    out = [
        (chahal, chahal_paragraphs()),
        (othman, othman_paras),
        (summary, summary_paras),
        (mccann, mccann_paras),
    ]
    # Inadmissible deportation decisions: two manifestly ill-founded, one non-exhaustion.
    for i, grounds in enumerate(
        [["manifestly_ill_founded"], ["manifestly_ill_founded"], ["non_exhaustion"]], start=1
    ):
        item = f"001-9000{i}"
        doc = _doc(
            item,
            f"DEPORTEE{i} v. THE UNITED KINGDOM",
            doc_type="decision",
            chamber="Chamber",
            date=f"200{i}-03-0{i}",
            articles=["3"],
            outcome="inadmissible",
            outcome_raw="Inadmissible",
            inadmissibility_grounds=grounds,
            inadmissibility_grounds_source="text",
            importance=4,
            application_numbers=[f"1000{i}/05"],
        )
        out.append(
            (
                doc,
                [
                    _para(item, "1", "His deportation would, he says, breach Article 3."),
                    _para(item, "2", "The removal order was upheld; the expulsion is due."),
                    _para(item, "3", "The application is declared inadmissible."),
                ],
            )
        )
    return out


def seed(conn) -> None:
    """Reset the schema and load the corpus with the fake embedder."""
    embedder = get_embedder("fake")
    reset(conn)
    for doc, paragraphs in corpus():
        upsert_document(conn, doc, paragraphs)
        chunks = [
            {
                "id": f"{doc['item_id']}:recursive:{i}",
                "doc_id": doc["item_id"],
                "strategy": "recursive",
                "text": p["text"],
                "paragraph_ids": [p["id"]],
                "token_count": len(p["text"].split()),
            }
            for i, p in enumerate(paragraphs)
        ]
        vectors = embedder.embed([c["text"] for c in chunks])
        replace_chunks(conn, doc["item_id"], "recursive", chunks, vectors, embedder.model_name)
    conn.execute("ANALYZE")
    conn.commit()
