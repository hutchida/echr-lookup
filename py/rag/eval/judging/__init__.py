"""Pooled relevance judging for the ECHR eval set (J1).

The draft answer key (data/eval/questions.jsonl) lists the paragraphs one agent thought answer each
question. This package checks whether that key is too narrow: it pools every paragraph any
retrieval config returns for a question (plus the key), has a different model grade each one, and
re-scores all configs against the resulting graded key ("qrels v2"). The original key is never
modified. Run it with `python -m rag.eval.judging --help`; see docs/eval-judging.md.
"""
