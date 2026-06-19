# Bonus — Day 17

Phiên brainstorm + prototype cho bài toán **KG hỏi-đáp văn bản pháp luật Việt Nam**.

## Nội dung

| File | Là gì |
|---|---|
| `DESIGN.md` | Bản brainstorm (1100+ từ): bài toán, 4 câu hỏi mở kèm đánh đổi, phương án bị loại, sơ đồ kiến trúc, bối cảnh VN |
| `legal_kg.py` | Prototype chạy được: trích dẫn chiếu → graph đa văn bản → multi-hop + point-in-time hiệu lực (ASOF) |
| `data/nd_giao_thong_sample.md` | Corpus *cố ý bẩn* (OCR-like, Điều→Khoản→Điểm lồng, dẫn chiếu chéo) |
| `data/hieu_luc.csv` | Bảng hiệu lực do người curate (cho ASOF point-in-time) |
| `test_legal_kg.py` | Test cho prototype legal-KG |
| `test_extensions.py` | Test cho extension #0 (fuzzy decontamination trong `pipeline/dataset.py`) |
| `test_data_contract.py` | Test cho extension #3 — chứng minh `../datacontract.yaml` không drift khỏi gate Pandera |
| `../datacontract.yaml` | Data contract chuẩn ODCS cho bảng orders (extension #3) |
| `crawl.py` | Stage ingest: crawl URL (từ `../data/urls.txt`) → markdown (trafilatura) → Bronze → RAG/KG sẵn có; idempotent theo content-hash |
| `test_crawl.py` | Test crawl OFFLINE (fake fetch, không cần mạng) |

## Chạy

```bash
python bonus/legal_kg.py        # demo: multi-hop dẫn chiếu + point-in-time hiệu lực
python -m pytest bonus -q       # chạy test bonus (nằm ngoài tests/ nên không đụng "18 passed" của core)
```

> Test data contract cần `pip install pyyaml`. Lint contract bằng CLI (tùy chọn):
> `pip install datacontract-cli && datacontract lint datacontract.yaml`.

### Crawl stage (URL → Markdown → Bronze → RAG/KG)

```bash
pip install -r requirements-crawl.txt    # trafilatura, zero-key
# sửa data/urls.txt (1 URL / dòng) rồi:
python bonus/crawl.py                     # hoặc: python bonus/crawl.py path/to/urls.txt
```

Crawl giữ HTML thô vào Bronze (`crawl_warehouse.duckdb`), ghi markdown vào
`data/crawled/`, rồi chạy `embed.py`/`kg.py` trên đó. **Idempotent**: chạy lần 2
bỏ qua doc không đổi (content-hash) — chạy lại/backfill an toàn, không nhân đôi.
Markdown crawl đổ vào `data/crawled/` (KHÔNG phải `data/docs/`) để không phá
fixtures của `verify.py`/`kg_demo`.

## Hai quyết định cốt lõi prototype minh hoạ

1. **Graph thắng vector trên multi-hop dẫn chiếu.** Mức phạt cho xe tải (Điều 6 k5)
   nằm ở *điều khác* (Điều 5 k5 điểm a). Không chunk nào chứa cả hai → vector top-k
   trả nửa chuỗi; graph đi đúng `Điều 6 k5 → Điều 5 k5 điểm a`.
2. **ASOF thắng "bản mới nhất" trên point-in-time hiệu lực.** Vi phạm 2024-06-01
   phải áp NĐ100/2019 (4–6tr), không phải NĐ168/2024 (6–8tr, hiệu lực 2025). Trả
   bản mới nhất = phạt hồi tố = sai luật. Đây là training-serving skew của lab, đặt
   vào nơi sai sót là một công dân bị phạt oan.

## Extension exercise kèm theo

`pipeline/dataset.decontaminate_fuzzy` (README ext. #0): decontamination khớp
n-gram, bắt được prompt eval bị *viết lại* mà `decontaminate` exact-match bỏ lọt.
Xem `test_extensions.py`.
