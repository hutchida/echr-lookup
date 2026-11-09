"""PDF text (pypdf, run ad hoc via `uv run --no-project --with pypdf`) -> data/raw/g0b/leg/conv_clean.txt.
Strips page-number-only lines and trailing spaces; keeps the ARTICLE N / title / numbered-paragraph layout."""

import re
from pathlib import Path

from pypdf import PdfReader

LEG = Path(__file__).resolve().parents[2] / "data" / "raw" / "g0b" / "leg"
text = "\n".join(p.extract_text() for p in PdfReader(LEG / "conv.pdf").pages)
lines = [ln.rstrip() for ln in text.splitlines()]
lines = [ln for ln in lines if not re.fullmatch(r"\s*\d{1,3}(\s+\d{1,3})?\s*", ln)]
out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"
(LEG / "conv_clean.txt").write_text(out, encoding="utf-8")
print(len(out))
