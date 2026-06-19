"""Tests for extensions #1 (real embeddings + incremental), #2 (LLM KG), #4 (backfill).

All OFFLINE and zero-key: the LLM client is faked, the embedder is the deterministic
hash fallback, the backfill reads the local CSV. Run:

    python -m pytest bonus/test_more_extensions.py -q
"""
import sys
import types
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_llm import extract_triples_llm, resolve_entities  # noqa: E402
from embed_real import incremental_embed, get_embedder  # noqa: E402
from backfill import backfill, SILVER  # noqa: E402

from pipeline.embed import embed_text  # noqa: E402


# ---------- ext #2: LLM KG ----------
def _fake_client(payload_json: str):
    """Minimal stand-in for anthropic.Anthropic() — no network."""
    block = types.SimpleNamespace(type="text", text=payload_json)
    resp = types.SimpleNamespace(content=[block])
    messages = types.SimpleNamespace(create=lambda **kw: resp)
    return types.SimpleNamespace(messages=messages)


def test_llm_extractor_parses_structured_output():
    client = _fake_client('{"triples": [{"subject": "Widgets", "relation": "IS A", "object": "the accessory"}]}')
    triples = extract_triples_llm("ignored", client=client)
    assert triples == [("Widgets", "IS A", "the accessory")]


def test_entity_resolution_collapses_surface_forms():
    triples = [("Widgets", "IS A", "the Accessory"), ("widget", "is_a", "accessory")]
    resolved = resolve_entities(triples)
    # plural/article/case all collapse to one canonical edge -> deduped to a single triple
    assert resolved == [("widget", "IS_A", "accessory")]


def test_entity_resolution_applies_alias_map():
    resolved = resolve_entities([("gizmos", "IS_A", "gadget")], aliases={"gizmo": "widget"})
    assert resolved == [("widget", "IS_A", "gadget")]


# ---------- ext #1: incremental embeddings ----------
def test_get_embedder_falls_back_without_model():
    embed_fn, label = get_embedder(prefer_real=False)
    assert label == "hash-fallback"
    assert len(embed_fn("hello")) > 0


def test_incremental_embed_only_embeds_changed_chunks(tmp_path):
    cache = tmp_path / "cache.json"
    chunks = ["alpha text", "beta text", "gamma text"]
    first = incremental_embed(chunks, cache, embed_text)
    assert first["embedded"] == 3 and first["reused"] == 0

    # re-run unchanged -> everything served from cache
    second = incremental_embed(chunks, cache, embed_text)
    assert second["embedded"] == 0 and second["reused"] == 3

    # edit one chunk -> exactly one re-embed
    chunks[1] = "beta text EDITED"
    third = incremental_embed(chunks, cache, embed_text)
    assert third["embedded"] == 1 and third["reused"] == 2


# ---------- ext #4: idempotent backfill ----------
def test_backfill_single_date_is_idempotent(tmp_path):
    con = duckdb.connect(str(tmp_path / "bf.duckdb"))
    try:
        first = backfill(con, date="2026-06-01")
        second = backfill(con, date="2026-06-01")        # replay
        assert first["silver_total"] == second["silver_total"]   # no duplication
        # only that date's rows are present
        dates = [r[0] for r in con.execute(f"SELECT DISTINCT created_at FROM {SILVER}").fetchall()]
        assert dates == ["2026-06-01"]
        # order_id 1 appears twice in raw on that date -> deduped to one
        (n_ord1,) = con.execute(f"SELECT count(*) FROM {SILVER} WHERE order_id = 1").fetchone()
        assert n_ord1 == 1
    finally:
        con.close()


def test_backfill_all_dates_quarantines_bad_rows(tmp_path):
    con = duckdb.connect(str(tmp_path / "bf2.duckdb"))
    try:
        result = backfill(con, date=None)
        assert result["quarantined"] == 3        # the null user_id, negative amount, bad status
        # re-running the full window stays stable
        again = backfill(con, date=None)
        assert again["silver_total"] == result["silver_total"]
    finally:
        con.close()
