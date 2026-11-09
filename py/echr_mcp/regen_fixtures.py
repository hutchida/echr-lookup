"""Regenerate the contract fixtures that hold real tool output, from the real database.

    cd py && uv run --group ml python -m echr_mcp.regen_fixtures

Runs search_case_law, get_paragraphs, get_case and check_quote on their `*Input.json` fixtures
against the configured database (the 98-document snapshot) and rewrites the matching
`packages/contract/fixtures/Mcp*Result.json`. Needs the real models; review `git diff` afterwards.
"""

from __future__ import annotations

import json

from echr_mcp import tools
from rag import config, index
from rag.contract import FIXTURE_DIR, load_fixture
from rag.search import get_reranker


def main() -> None:
    embedder = index.get_embedder()
    reranker = get_reranker() if config.rerank_enabled() else None
    with index.connect() as conn:
        results = {
            "McpSearchCaseLawResult": tools.search_case_law(
                conn, load_fixture("McpSearchCaseLawInput"), embedder=embedder, reranker=reranker
            ),
            "McpGetParagraphsResult": tools.get_paragraphs(
                conn, load_fixture("McpGetParagraphsInput")
            ),
            "McpGetCaseResult": tools.get_case(conn, load_fixture("McpGetCaseInput")),
            "McpCheckQuoteResult": tools.check_quote(conn, load_fixture("McpCheckQuoteInput")),
        }
    for name, result in results.items():
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        (FIXTURE_DIR / f"{name}.json").write_text(text)
        print(f"wrote fixtures/{name}.json")


if __name__ == "__main__":
    main()
