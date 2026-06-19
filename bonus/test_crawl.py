"""Tests for the crawl stage. OFFLINE — network is faked with a fixture so the
test is deterministic. Needs trafilatura (`pip install -r requirements-crawl.txt`).

    python -m pytest bonus/test_crawl.py -q
"""
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crawl import extract_markdown, crawl_to_bronze, read_urls, BRONZE_DOCS  # noqa: E402

FIXTURE_HTML = """
<html><head><title>Returns Policy</title></head><body>
<nav>home | about | ads everywhere</nav>
<article>
<h1>Chính sách đổi trả</h1>
<p>Khách hàng có thể trả lại widget trong vòng 30 ngày để được hoàn tiền đầy đủ.</p>
<p>Gadget được bảo hành 90 ngày cho lỗi của nhà sản xuất.</p>
<p>Sprocket là hàng bán cuối cùng và không thể trả lại sau khi đã mở.</p>
</article>
<footer>copyright boilerplate junk</footer>
</body></html>
"""


def test_extract_strips_boilerplate_to_markdown():
    md = extract_markdown(FIXTURE_HTML)
    assert md, "expected markdown output"
    assert "widget trong vòng 30 ngày" in md       # main content kept
    assert "ads everywhere" not in md               # nav/footer boilerplate dropped
    assert "copyright boilerplate" not in md


def test_extract_returns_none_on_empty():
    assert extract_markdown(None) is None
    assert extract_markdown("") is None


def test_crawl_lands_bronze_and_is_idempotent(tmp_path):
    urls = ["https://example.com/policy", "https://example.com/policy2"]
    fake = lambda url: FIXTURE_HTML            # noqa: E731 -- inject fixture, no network
    con = duckdb.connect(":memory:")
    try:
        first = crawl_to_bronze(con, urls, docs_dir=tmp_path, fetch_fn=fake)
        # both URLs yield the SAME content -> first new, second a content-hash dupe
        assert first["new"] == 1
        assert first["dupe"] == 1
        assert first["bronze_rows"] == 1

        # a .md file was written for the doc that landed
        assert list(Path(tmp_path).glob("*.md"))

        # re-run = backfill: no new rows, nothing duplicated (idempotent)
        second = crawl_to_bronze(con, urls, docs_dir=tmp_path, fetch_fn=fake)
        assert second["new"] == 0
        assert second["bronze_rows"] == 1

        # Bronze kept the raw HTML verbatim (Medallion rule #1)
        (html,) = con.execute(f"SELECT raw_html FROM {BRONZE_DOCS} LIMIT 1").fetchone()
        assert "<article>" in html
    finally:
        con.close()


def test_read_urls_skips_comments_and_blanks(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text("# comment\n\nhttps://a.com\n  https://b.com  \n# end\n", encoding="utf-8")
    assert read_urls(f) == ["https://a.com", "https://b.com"]
