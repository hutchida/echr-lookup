"""CLI: python -m rag.ingest --source snapshot|full [--limit N] [--reset]."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import FULL_ROOT, run_ingest
from .full import ListingLoopError
from .hudoc import BLOCK_INSTRUCTIONS, HudocBlocked, HudocClient, HudocUnavailable, OrcaTransport
from .ratelimit import DEFAULT_HARD_CAP, MIN_INTERVAL, RateLimiter, RequestCapReached


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rag.ingest", description=__doc__)
    ap.add_argument("--source", choices=["snapshot", "full"], required=True)
    ap.add_argument("--limit", type=int, default=None, help="only the first N documents")
    ap.add_argument("--reset", action="store_true", help="empty the database first")
    ap.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="full mode: stop after this many HUDOC requests in this run",
    )
    ap.add_argument("--page", default=None, help="full mode: Orca browser page id of a HUDOC tab")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("rag.ingest").setLevel(logging.INFO)

    from rag import index

    client = None
    if args.source == "full":
        limiter = RateLimiter(
            FULL_ROOT,
            min_interval=float(os.environ.get("HUDOC_MIN_INTERVAL", MIN_INTERVAL)),
            hard_cap=int(os.environ.get("HUDOC_HARD_CAP", DEFAULT_HARD_CAP)),
            run_cap=args.max_requests,
        )
        client = HudocClient(OrcaTransport(args.page), limiter, FULL_ROOT / "hudoc-requests.jsonl")

    with index.connect() as conn:
        try:
            run_ingest(conn, args.source, limit=args.limit, reset=args.reset, client=client)
        except HudocBlocked as exc:
            print("\nSTOPPED: " + BLOCK_INSTRUCTIONS.format(reason=exc), file=sys.stderr)
            return 2
        except RequestCapReached as exc:
            print(
                f"\nSTOPPED: {exc}. Downloads so far are kept; re-run to continue.", file=sys.stderr
            )
            return 2
        except ListingLoopError as exc:
            print(f"\nSTOPPED: {exc}", file=sys.stderr)
            return 2
        except HudocUnavailable as exc:
            print(f"\nSTOPPED: cannot reach HUDOC through Orca's browser: {exc}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
