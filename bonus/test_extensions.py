"""Tests for the lab extension exercises. Zero-key.

Run from the repo root (kept OUT of tests/ so the graded `pytest -q` stays at 18):

    python -m pytest bonus -q
"""
from pipeline.dataset import decontaminate, decontaminate_fuzzy

EVAL = [{"input": "Can I return a widget I bought 10 days ago?", "reference": "Yes.", "trace_id": "t"}]

# A paraphrase of the eval prompt + a genuinely unrelated training prompt.
PAIRS = [
    {"prompt": "Is it possible to return a widget purchased 10 days ago?",
     "chosen": "Yes, within 30 days.", "rejected": "No."},
    {"prompt": "How long is the gadget warranty?",
     "chosen": "90 days.", "rejected": "Forever."},
]


def test_exact_match_misses_the_paraphrase():
    # the graded exact-match decontaminator leaks: the reworded eval prompt survives
    kept = decontaminate(PAIRS, EVAL)
    assert len(kept) == 2
    assert any("possible to return a widget" in p["prompt"] for p in kept)


def test_fuzzy_drops_the_paraphrase_but_keeps_unrelated():
    kept = decontaminate_fuzzy(PAIRS, EVAL)
    prompts = [p["prompt"] for p in kept]
    # the reworded eval prompt is now caught and removed...
    assert not any("possible to return a widget" in p for p in prompts)
    # ...while the unrelated warranty prompt is preserved
    assert any("gadget warranty" in p for p in prompts)


def test_fuzzy_is_a_noop_when_eval_set_is_empty():
    assert decontaminate_fuzzy(PAIRS, []) == PAIRS
