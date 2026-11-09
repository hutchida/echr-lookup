"""Compare HTML / DOCX / PDF as a parse source: how many of the numbered paragraphs does each recover?
Run: uv run --with pypdf python ../scripts/g0b/analyse_formats.py"""

import json
import re
import sys
import time
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).parent))
from proto_parse import completeness, parse_docx, parse_html  # noqa: E402

F = Path(__file__).resolve().parents[2] / "data" / "raw" / "g0b" / "formats"
ids = sorted({p.stem for p in F.glob("*.html")})
rows = []
for i in ids:
    h = parse_html(F / f"{i}.html")
    ch = completeness(h)
    t0 = time.perf_counter()
    d = parse_docx(F / f"{i}.docx")
    td = time.perf_counter() - t0
    cd = completeness(d)
    t0 = time.perf_counter()
    text = "\n".join(p.extract_text() for p in PdfReader(F / f"{i}.pdf").pages)
    tp = time.perf_counter() - t0
    pdf_nums = []
    last = 0
    for ln in text.splitlines():
        m = re.match(r"^\s*(\d{1,3})\.\s+\S", ln)
        if m and int(m.group(1)) == last + 1:
            last = int(m.group(1))
            pdf_nums.append(last)
    rows.append(
        {
            "id": i,
            "html_numbered": ch["n_numbered"],
            "html_max": ch["max"],
            "docx_numbered": cd["n_numbered"],
            "docx_gaps_vs_html": ch["n_numbered"] - cd["n_numbered"],
            "pdf_numbered": len(pdf_nums),
            "html_bytes": (F / f"{i}.html").stat().st_size,
            "docx_bytes": (F / f"{i}.docx").stat().st_size,
            "pdf_bytes": (F / f"{i}.pdf").stat().st_size,
            "docx_parse_s": td,
            "pdf_extract_s": tp,
        }
    )
    print(rows[-1])
(F / "analysis.json").write_text(json.dumps(rows, indent=1))
