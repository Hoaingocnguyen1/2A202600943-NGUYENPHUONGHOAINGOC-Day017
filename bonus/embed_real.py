"""Extension #1 — real embeddings + incremental re-embed by content hash.

The lab's embed.py uses a deterministic hash 'embedder' (zero-key, no download) so
the pipeline shape is the point, not embedding quality. This extension:

  * swaps in a real local sentence-transformers model (multilingual — works on
    Vietnamese) when available, falling back to the lab's hash embedder otherwise;
  * adds INCREMENTAL re-embedding keyed on a content hash, so re-running only embeds
    chunks whose text changed — the expensive step (model inference) is skipped for
    everything unchanged (README ext. #1, deck §3).

The incremental cache logic is independent of which embedder runs, so it's tested
with the deterministic embedder (no model download, no key).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.embed import embed_text as _hash_embed, recursive_chunks  # reuse the lab's splitter

# A small multilingual model with good Vietnamese coverage; downloaded once on first use.
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def get_embedder(prefer_real: bool = True, model_name: str = DEFAULT_MODEL):
    """Return (embed_fn, label). Real model if installed+prefer_real, else hash fallback."""
    if prefer_real:
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(model_name)
            return (lambda text: [round(float(x), 6) for x in model.encode(text)]), f"st:{model_name}"
        except Exception:
            pass  # not installed / offline -> fall back, stay zero-key
    return _hash_embed, "hash-fallback"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def incremental_embed(chunks: list[str], cache_path: Path | str, embed_fn=_hash_embed) -> dict:
    """Embed only chunks whose content hash is not already cached. Returns rows + stats.

    The cache is {content_hash: vector} on disk. Re-running after editing one chunk
    re-embeds exactly that chunk; everything else is served from cache. This is the
    same content-hash change-detection the crawl stage uses for idempotency.
    """
    cache_path = Path(cache_path)
    cache: dict[str, list[float]] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    rows, embedded, reused = [], 0, 0
    for idx, chunk in enumerate(chunks):
        h = _hash(chunk)
        if h in cache:
            reused += 1
        else:
            cache[h] = embed_fn(chunk)
            embedded += 1
        rows.append({"chunk_id": idx, "content_hash": h, "text": chunk, "embedding": cache[h]})

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return {"rows": rows, "embedded": embedded, "reused": reused, "cache_size": len(cache)}


def main() -> dict:
    from pipeline import config

    embed_fn, label = get_embedder(prefer_real=True)
    text = (config.DOCS_DIR / "sample.md").read_text(encoding="utf-8")
    chunks = recursive_chunks(text)
    cache = config.ROOT / "embed_cache.json"

    first = incremental_embed(chunks, cache, embed_fn)
    second = incremental_embed(chunks, cache, embed_fn)  # re-run: should all be reused

    print("=== Ext #1: real embeddings + incremental re-embed ===")
    print(f"  embedder            : {label}")
    print(f"  chunks              : {len(chunks)}")
    print(f"  run 1: embedded={first['embedded']} reused={first['reused']}")
    print(f"  run 2: embedded={second['embedded']} reused={second['reused']}  (incremental cache hit)")
    return {"embedder": label, "chunks": len(chunks),
            "first_embedded": first["embedded"], "second_embedded": second["embedded"]}


if __name__ == "__main__":
    main()
