"""G0b: try HTML/DOCX/PDF conversion endpoints on a few documents; save raw bodies under
data/raw/g0b/formats/ (gitignored) and log status/size/time."""

import json
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
from hudoc import Hudoc  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "data" / "raw" / "g0b" / "formats"
OUT.mkdir(parents=True, exist_ok=True)
IDS = sys.argv[1:] or [
    "001-57619",
    "001-176931",
    "001-98645",
    "001-70442",
    "002-14577",
    "001-243879",
]


def main() -> None:
    h = Hudoc()
    rows = []
    for i in IDS:
        for fmt, path, ext in [
            ("html", f"/app/conversion/docx/html/body?library=ECHR&id={i}", "html"),
            (
                "docx",
                f"/app/conversion/docx/?library=ECHR&id={i}&filename={quote('doc.docx')}&logEvent=False",
                "docx",
            ),
            (
                "pdf",
                f"/app/conversion/pdf/?library=ECHR&id={i}&filename={quote('doc.pdf')}&logEvent=False",
                "pdf",
            ),
        ]:
            r = h.get(path, tag=f"format-{fmt}")
            (OUT / f"{i}.{ext}").write_bytes(r.content)
            rows.append(
                {
                    "id": i,
                    "fmt": fmt,
                    "status": r.status_code,
                    "bytes": len(r.content),
                    "secs": round(r.secs, 3),
                    "ctype": r.content_type,
                }
            )
            print(rows[-1], flush=True)
    (OUT / "formats.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
