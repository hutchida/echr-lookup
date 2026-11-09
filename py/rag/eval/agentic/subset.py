"""The fixed retrieval subset: 30 questions drawn with a seeded RNG, committed as ids."""

import json
import random

from rag.eval.items import QUESTIONS_PATH, load_questions

from .common import SUBSET_PATH, SUBSET_SEED, SUBSET_SIZE


def draw_subset(seed: int = SUBSET_SEED, size: int = SUBSET_SIZE) -> dict:
    population = [i for i in load_questions(QUESTIONS_PATH) if i.get("expected_paragraph_ids")]
    ids = [i["id"] for i in random.Random(seed).sample(population, size)]
    return {
        "seed": seed,
        "size": size,
        "method": "random.Random(seed).sample(items of data/eval/questions.jsonl, in file order, "
        "that have non-empty expected_paragraph_ids, size)",
        "population": len(population),
        "ids": ids,
    }


def write_subset() -> dict:
    subset = draw_subset()
    SUBSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUBSET_PATH.write_text(json.dumps(subset, indent=2) + "\n")
    return subset
