"""A cheap token counter for tests and CI (no ML packages)."""

from __future__ import annotations

import math
import re

_PIECE = re.compile(r"\w+|[^\w\s]")

# WordPiece (bge) splits rare words into several pieces, so words + punctuation marks under-counts.
# The factor is chosen from a measurement against the real bge-small tokenizer over the whole
# snapshot (see docs/learn/S2.md) so that it over-counts: a chunk that fits under this counter also
# fits under the real one.
APPROX_FACTOR = 1.25


def approx_count_tokens(text: str) -> int:
    """Words + punctuation marks, scaled up and rounded up (so joining texts never shrinks it)."""
    return math.ceil(len(_PIECE.findall(text)) * APPROX_FACTOR)
