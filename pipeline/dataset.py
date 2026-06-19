"""Thực Hành 4 — Eval & preference datasets curated from agent traces.

Once agent turns live in Bronze (see traces.py), they become training data:

  * golden eval set   — (input -> reference output) from turns that SUCCEEDED.
  * preference pairs   — (prompt, chosen, rejected) where `chosen` is a good
                         answer and `rejected` is a failed/refused answer to the
                         SAME question. This is exactly the (x, y_w, y_l) format
                         DPO/ORPO consume on Day 22.

The decontamination step is the part students always skip and regret: any prompt
that appears in the eval set is removed from the preference (training) set, so we
never train on what we grade on. Train/test leakage is the #1 way an eval lies.
"""
from __future__ import annotations
import json
from pathlib import Path

import duckdb

from .traces import BRONZE_SPANS


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def build_eval_set(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Golden eval rows = the human-curated holdout (split='eval') of
    successful turns: {input, reference, trace_id}. Kept OUT of training."""
    rows = con.execute(
        f"""
        SELECT trace_id, user_input, agent_output
        FROM {BRONZE_SPANS}
        WHERE depth = 0 AND status = 'ok' AND split = 'eval'
              AND user_input IS NOT NULL AND agent_output IS NOT NULL
        ORDER BY trace_id
        """
    ).fetchall()
    return [
        {"trace_id": t, "input": i, "reference": o}
        for (t, i, o) in rows
    ]


def build_preference_pairs(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Pair a good (ok) answer with a bad (error) answer to the SAME question.

    `chosen`  = output of a successful turn for that input.
    `rejected` = output of a failed/refused turn for that same input.
    Yields the (prompt, chosen, rejected) triple DPO/ORPO expect (Day 22).
    """
    roots = con.execute(
        f"""
        SELECT user_input, status, agent_output
        FROM {BRONZE_SPANS}
        WHERE depth = 0 AND user_input IS NOT NULL
        """
    ).fetchall()

    good: dict[str, str] = {}
    bad: dict[str, str] = {}
    for user_input, status, output in roots:
        key = _norm(user_input)
        if status == "ok":
            good.setdefault(key, output)
        else:
            bad.setdefault(key, output)

    pairs = []
    for key in sorted(set(good) & set(bad)):
        pairs.append({"prompt": key, "chosen": good[key], "rejected": bad[key]})
    return pairs


def decontaminate(pairs: list[dict], eval_set: list[dict]) -> list[dict]:
    """Drop any preference pair whose prompt is also an eval input (no leakage).

    NOTE: this is EXACT-match decontamination (after lowercase + whitespace
    normalization). A reworded or paraphrased duplicate still leaks — production
    pipelines add n-gram (e.g. 13-gram) or embedding-similarity matching. See the
    'fuzzy decontamination' extension exercise.
    """
    held_out = {_norm(e["input"]) for e in eval_set}
    return [p for p in pairs if _norm(p["prompt"]) not in held_out]


def _word_ngrams(s: str, n: int) -> set[tuple[str, ...]]:
    """Normalized word n-grams. Short strings fall back to the whole token tuple."""
    toks = _norm(s).split()
    if len(toks) < n:
        return {tuple(toks)} if toks else set()
    return {tuple(toks[i : i + n]) for i in range(len(toks) - n + 1)}


def decontaminate_fuzzy(
    pairs: list[dict], eval_set: list[dict], n: int = 3, threshold: float = 0.2
) -> list[dict]:
    """Extension (README ext. #0) — fuzzy decontamination that catches REWORDED leaks.

    The graded `decontaminate` is exact-match (after normalization): a paraphrased
    eval prompt — "Can I return a widget I bought 10 days ago?" rewritten as "Is it
    possible to return a widget purchased 10 days ago?" — slips straight through and
    silently contaminates the training set. This compares word n-gram sets with the
    *overlap coefficient* |A∩B| / min(|A|,|B|); a pair is dropped if it overlaps any
    eval input above `threshold`. Sharing a 3-gram like ('return','a','widget') is a
    strong contamination signal that exact match never sees.

    Production scales this further: 13-gram matching for long-document pretrain
    decontamination, or embedding cosine (reuse `embed.embed_text`) to catch
    semantic paraphrase the n-gram view still misses. n and threshold are tunable —
    higher n / threshold = fewer false drops but more leaks slip through.
    """
    eval_grams = [g for e in eval_set if (g := _word_ngrams(e["input"], n))]
    if not eval_grams:
        return list(pairs)
    kept = []
    for p in pairs:
        pg = _word_ngrams(p["prompt"], n)
        if not pg:
            kept.append(p)
            continue
        leaked = any(
            len(pg & eg) / min(len(pg), len(eg)) >= threshold for eg in eval_grams
        )
        if not leaked:
            kept.append(p)
    return kept


def write_jsonl(rows: list[dict], path: Path) -> int:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)
