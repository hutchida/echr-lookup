"""Try the parser from the command line.

uv run python -m rag.parse 001-57619 --summary
uv run python -m rag.parse 001-57619 --para 88
uv run python -m rag.parse 001-57619 --para 111 --para op1
uv run python -m rag.parse 001-57619 --chunks recursive
uv run python -m rag.parse path/to/file.html
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from collections import Counter
from pathlib import Path

from rag.config import REPO_ROOT, data_dir

from . import STRATEGIES, chunk_paragraphs, parse_document

SNAPSHOT = REPO_ROOT / "data" / "snapshot"


def _load_manifest() -> list[tuple[Path, dict]]:
    out = []
    for root in dict.fromkeys([SNAPSHOT, data_dir()]):
        manifest = root / "manifest.json"
        if manifest.exists():
            out += [(root, e) for e in json.loads(manifest.read_text())]
    return out


def resolve(target: str) -> tuple[dict, bytes]:
    """An item id from the manifest, or a path to a stored HUDOC .html / .xml / .txt file."""
    manifest = _load_manifest()
    path = Path(target)
    for root, entry in manifest:
        if entry["item_id"] == target or (
            path.exists() and (root / entry["path"]).resolve() == path.resolve()
        ):
            return entry, (root / entry["path"]).read_bytes()
    if not path.exists():
        raise SystemExit(f"not an item id in the manifest, and not a file: {target}")
    fmt = {".html": "html", ".xml": "xml", ".txt": "txt"}.get(path.suffix)
    if fmt is None:
        raise SystemExit(f"cannot parse {path.suffix!r} files (use .html, .xml or .txt)")
    item_id = path.stem
    doc_type = (
        "legislation"
        if fmt != "html"
        else "legal_summary"
        if item_id.startswith("002-")
        else "judgment"
    )
    entry = {
        "item_id": item_id, "case_name": item_id, "application_numbers": [], "ecli": None,
        "doc_type": doc_type, "chamber": None, "date": "1970-01-01", "articles": [],
        "outcome_raw": None, "outcome": "other", "inadmissibility_grounds": None,
        "inadmissibility_grounds_source": None, "importance": None, "language": "en",
        "source_url": "https://example.org/", "sha256": "0" * 64, "data_source": "snapshot",
        "format": fmt,
    }  # fmt: skip
    return entry, path.read_bytes()


def _wrap(text: str, indent: str = "    ") -> str:
    return "\n".join(
        textwrap.fill(line, width=100, initial_indent=indent, subsequent_indent=indent)
        for line in text.split("\n")
    )


def show_summary(doc: dict, paras: list[dict]) -> None:
    meta = f"{doc['doc_type']}, {doc['date']}, {doc['outcome']}"
    print(f"{doc['item_id']}  {doc['case_name']}  ({meta})")
    print(f"{len(paras)} paragraphs, {sum(len(p['text']) for p in paras):,} characters")
    if doc.get("inadmissibility_grounds"):
        print(
            f"inadmissibility grounds ({doc['inadmissibility_grounds_source']}): "
            + ", ".join(doc["inadmissibility_grounds"])
        )
    groups: list[list] = []
    for p in paras:
        ref = p["id"].split("§", 1)[1]
        if groups and groups[-1][0] == p["section"]:
            groups[-1][1].append(ref)
        else:
            groups.append([p["section"], [ref]])
    print(f"\n{'section':<22}{'paragraphs':>10}  first .. last")
    for section, refs in groups:
        print(f"{section:<22}{len(refs):>10}  §{refs[0]} .. §{refs[-1]}")
    kinds = Counter(
        "numbered" if p["number"] else "op" if "§op" in p["id"] else "other" for p in paras
    )
    print(f"\n{dict(kinds)}")


def show_paragraphs(doc: dict, paras: list[dict], wanted: list[str]) -> int:
    by_ref = {p["id"].split("§", 1)[1]: p for p in paras}
    missing = 0
    for w in wanted:
        ref = w.split("§", 1)[-1]
        p = by_ref.get(ref)
        if p is None:
            print(f"no paragraph §{ref} in {doc['item_id']} (try --summary)", file=sys.stderr)
            missing += 1
            continue
        print(f"{p['id']}  [{p['section']}]")
        print(_wrap(p["text"]))
        print()
    return missing


def show_chunks(paras: list[dict], strategy: str, max_tokens: int, counter) -> None:
    chunks = chunk_paragraphs(paras, strategy, count_tokens=counter, max_tokens=max_tokens)
    print(f"{len(chunks)} {strategy} chunks")
    print(f"{'chunk':<28}{'tokens':>6}  {'paragraphs':<22}starts with")
    for c in chunks:
        refs = [i.split("§", 1)[1] for i in c["paragraph_ids"]]
        span = f"§{refs[0]}" if len(refs) == 1 else f"§{refs[0]}..§{refs[-1]} ({len(refs)})"
        print(f"{c['id']:<28}{c['token_count']:>6}  {span:<22}{c['text'][:60]!r}")


def _real_counter():
    try:
        from transformers import AutoTokenizer
    except ImportError:
        raise SystemExit("--real-tokens needs: uv sync --group ml") from None
    tok = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5")
    return lambda text: len(tok.encode(text, add_special_tokens=True))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rag.parse", description=__doc__.split("\n\n")[0])
    ap.add_argument("target", help="item id from the snapshot manifest, or a path to a stored file")
    ap.add_argument(
        "--para", action="append", default=[], help="paragraph to print: 88, op1, u3, art8"
    )
    ap.add_argument("--chunks", choices=STRATEGIES, help="show chunk boundaries for a strategy")
    ap.add_argument("--max-tokens", type=int, default=256, help="chunk size for fixed / recursive")
    ap.add_argument("--real-tokens", action="store_true", help="count with the bge-small tokenizer")
    ap.add_argument("--summary", action="store_true", help="sections and paragraph counts")
    args = ap.parse_args(argv)

    entry, raw = resolve(args.target)
    parsed = parse_document(entry, raw)
    doc, paras = parsed["document"], parsed["paragraphs"]
    status = 0
    if args.summary or not (args.para or args.chunks):
        show_summary(doc, paras)
    if args.para:
        status = show_paragraphs(doc, paras, args.para)
    if args.chunks:
        counter = _real_counter() if args.real_tokens else None
        show_chunks(paras, args.chunks, args.max_tokens, counter)
    return 1 if status else 0


if __name__ == "__main__":
    sys.exit(main())
