"""Bonus stage — crawl URLs -> parse to Markdown -> Bronze -> reuse RAG/KG.

    python bonus/crawl.py                    # reads data/urls.txt
    python bonus/crawl.py path/to/urls.txt

The real-world front of the unstructured pipeline (deck §3): the lab ships clean
local docs, but production data arrives as messy web pages. This stage:

    urls.txt -> fetch (trafilatura) -> extract main content as Markdown
             -> land in Bronze (raw HTML kept, append-only)  -> write .md
             -> the EXISTING embed.py (RAG) and kg.py (KG) consume the .md

Design choices that matter here:
  * Bronze keeps the raw HTML verbatim (Medallion rule #1) so any parse bug is
    rebuildable — we never lose the source.
  * Idempotent by content hash: re-running (or backfilling) the same URLs adds NO
    duplicate Bronze rows and rewrites nothing unchanged (extension #4 — safe
    re-runs). Change detection is the same content-hash trick as incremental
    re-embedding (extension #1).
  * Crawled Markdown lands in data/crawled/, NOT data/docs/, so the graded
    verify.py / kg_demo fixtures stay untouched; we point the existing RAG/KG
    functions at the new dir to prove they consume real crawled data unchanged.

Zero-key (trafilatura needs no API key). `pip install -r requirements-crawl.txt`.
Be a good citizen: respect robots.txt / a site's ToS and rate-limit real crawls.
"""
from __future__ import annotations

import hashlib
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow `python bonus/crawl.py`
from pipeline import config
from pipeline.embed import ingest_docs as embed_ingest
from pipeline.kg import ingest_docs_to_graph

ROOT = config.ROOT
URLS_FILE = ROOT / "data" / "urls.txt"
CRAWLED_DIR = ROOT / "data" / "crawled"
CRAWL_WAREHOUSE = ROOT / "crawl_warehouse.duckdb"   # persisted so re-runs are idempotent
BRONZE_DOCS = "bronze_crawled_docs"


def read_urls(path: Path | str = URLS_FILE) -> list[str]:
    """One URL per line; '#' comments and blank lines ignored."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [s.strip() for s in lines if s.strip() and not s.strip().startswith("#")]


def fetch_url(url: str) -> str | None:
    """Fetch raw HTML. Isolated so tests can inject a fixture instead of network."""
    import trafilatura

    return trafilatura.fetch_url(url)


def extract_markdown(html: str | None, url: str | None = None) -> str | None:
    """Extract the main content as Markdown (drops nav/ads/boilerplate)."""
    if not html:
        return None
    import trafilatura

    try:
        md = trafilatura.extract(
            html, output_format="markdown", include_tables=True,
            include_links=True, favor_recall=True,
        )
    except (TypeError, ValueError):
        md = trafilatura.extract(html, include_formatting=True, favor_recall=True)
    return md or None


def _slug(url: str) -> str:
    s = re.sub(r"^https?://", "", url)
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return (s[:80] or "doc")


def _ensure_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        f"""CREATE TABLE IF NOT EXISTS {BRONZE_DOCS} (
                url VARCHAR, fetched_at VARCHAR, content_hash VARCHAR,
                n_chars INTEGER, raw_html VARCHAR, markdown VARCHAR)"""
    )


def crawl_to_bronze(
    con: duckdb.DuckDBPyConnection,
    urls: list[str],
    docs_dir: Path | str = CRAWLED_DIR,
    fetch_fn=fetch_url,
    write_docs: bool = True,
    polite_delay: float = 0.0,
) -> dict:
    """Fetch + parse each URL into Bronze (append-only) and a .md file.

    Idempotent: a row whose Markdown content_hash already exists in Bronze is
    skipped (no duplicate row, no file rewrite) — safe to re-run / backfill.
    """
    _ensure_table(con)
    seen = {r[0] for r in con.execute(f"SELECT content_hash FROM {BRONZE_DOCS}").fetchall()}
    docs_dir = Path(docs_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)

    new = dupe = failed = 0
    for url in urls:
        html = fetch_fn(url)
        md = extract_markdown(html, url)
        if not md:                                   # fetch/parse failed -> count, don't crash
            failed += 1
            continue
        chash = hashlib.sha256(md.encode("utf-8")).hexdigest()[:16]
        if chash in seen:                            # idempotency guard
            dupe += 1
            continue
        seen.add(chash)
        con.execute(
            f"INSERT INTO {BRONZE_DOCS} VALUES (?,?,?,?,?,?)",
            [url, datetime.now(timezone.utc).isoformat(timespec="seconds"),
             chash, len(md), str(html), md],
        )
        if write_docs:
            (docs_dir / f"{_slug(url)}.md").write_text(md, encoding="utf-8")
        new += 1
        if polite_delay:
            time.sleep(polite_delay)

    (total,) = con.execute(f"SELECT count(*) FROM {BRONZE_DOCS}").fetchone()
    return {"urls": len(urls), "new": new, "dupe": dupe, "failed": failed, "bronze_rows": total}


def main(urls_path: Path | str = URLS_FILE) -> dict:
    urls = read_urls(urls_path)
    con = duckdb.connect(str(CRAWL_WAREHOUSE))     # persisted Bronze -> re-runs skip unchanged
    try:
        summary = crawl_to_bronze(con, urls, polite_delay=1.0)
        # downstream: the EXISTING RAG + KG stages consume the crawled markdown
        chunks = embed_ingest(CRAWLED_DIR)
        graph = ingest_docs_to_graph(CRAWLED_DIR)

        print("=== Bonus: crawl -> Bronze -> RAG/KG ===")
        print(f"  urls read           : {summary['urls']}")
        print(f"  new docs landed     : {summary['new']}  (Bronze rows: {summary['bronze_rows']})")
        print(f"  skipped (unchanged) : {summary['dupe']}  (idempotent re-run)")
        print(f"  failed fetch/parse  : {summary['failed']}")
        print(f"  RAG chunks embedded : {len(chunks)}  (from data/crawled/*.md)")
        print(f"  KG nodes extracted  : {len(graph)}")
        return {**summary, "chunks": len(chunks), "kg_nodes": len(graph)}
    finally:
        con.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else URLS_FILE)
