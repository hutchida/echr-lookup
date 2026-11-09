"""Download the HTML body of every curated candidate to data/raw/g0b/pool/ (gitignored)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hudoc import Hudoc  # noqa: E402
from snapshot_ids import DECISIONS_POOL, JUDGMENTS, LEGAL_SUMMARIES  # noqa: E402

POOL = Path(__file__).resolve().parents[2] / "data" / "raw" / "g0b" / "pool"
POOL.mkdir(parents=True, exist_ok=True)


def main() -> None:
    h = Hudoc()
    ids = [*JUDGMENTS, *DECISIONS_POOL, *LEGAL_SUMMARIES]
    log = []
    for i in ids:
        f = POOL / f"{i}.html"
        if f.exists() and f.stat().st_size > 1000:
            continue
        r = h.get(f"/app/conversion/docx/html/body?library=ECHR&id={i}", tag="snapshot-html")
        if r.status_code != 200 or len(r.content) < 1000:
            print("FAIL", i, r.status_code, len(r.content), flush=True)
            log.append({"id": i, "status": r.status_code})
            continue
        f.write_bytes(r.content)
        log.append({"id": i, "status": r.status_code, "bytes": len(r.content), "secs": r.secs})
        print(i, len(r.content), flush=True)
    (POOL / "_download_log.json").write_text(json.dumps(log, indent=1))


if __name__ == "__main__":
    main()
