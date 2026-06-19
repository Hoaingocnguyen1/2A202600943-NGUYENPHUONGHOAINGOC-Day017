# Hướng dẫn chạy demo & test (Windows / PowerShell)

> Khớp với máy đã set up: `.venv` (đường lite) + `.venv-dbt` (track dbt), Python 3.12.
> Chạy mọi lệnh từ thư mục gốc repo. Nếu dùng Git Bash/macOS/Linux, đổi
> `.\.venv\Scripts\python.exe` → `.venv/bin/python`.

---

## 0. Cài đặt (chỉ làm 1 lần)

```powershell
# Đường lite (phần chấm điểm chính) — Python 3.10+
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Track dbt (tùy chọn) — Python 3.10–3.13
python -m venv .venv-dbt
.\.venv-dbt\Scripts\python.exe -m pip install -r requirements-dbt.txt
```

> Nếu console hiện lỗi font tiếng Việt, đặt: `$env:PYTHONIOENCODING="utf-8"`

---

## 1. Đường lite — Medallion + Flywheel + KG

| Lệnh | Làm gì | Kỳ vọng |
|---|---|---|
| `.\.venv\Scripts\python.exe verify.py` | Smoke test end-to-end | **16/16 checks — ALL PASS** |
| `.\.venv\Scripts\python.exe main.py` | Pipeline Medallion (dedup + quarantine + Gold) | dropped=5, quarantined=3 |
| `.\.venv\Scripts\python.exe flywheel.py` | Agent traces → Bronze → eval/DPO + point-in-time | 21 spans, 2 eval, 3→1 cặp, 2 leaky |
| `.\.venv\Scripts\python.exe kg_demo.py` | Knowledge graph vs vector RAG | multi-hop widget→accessory→Hanoi |

---

## 2. Bonus — Legal KG (văn bản pháp luật VN)

```powershell
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe bonus\legal_kg.py
```

Kỳ vọng: in ra 10 cạnh dẫn chiếu/sửa đổi (3 văn bản), chuỗi multi-hop
`NĐ100:đ6.k5 → NĐ100:đ5.k5.đa`, và point-in-time:
- vi phạm **2024-06-01** → 4–6 triệu (NĐ100/2019) ✅ đúng
- "bản mới nhất" → 6–8 triệu (NĐ168/2024) ❌ phạt hồi tố

Đọc thiết kế: `bonus/DESIGN.md`. Chi tiết: `bonus/README.md`.

### Crawl URL → Markdown → Bronze → RAG/KG

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-crawl.txt   # trafilatura
# sửa data\urls.txt (1 URL / dòng), rồi:
.\.venv\Scripts\python.exe bonus\crawl.py
```

Kỳ vọng: crawl URL → giữ HTML thô vào Bronze (`crawl_warehouse.duckdb`) + ghi
`data\crawled\*.md` → embed RAG. Chạy lần 2: `skipped` = số doc không đổi
(idempotent, không nhân đôi).

---

## 3. Chạy test

```powershell
# Test core (phần chấm điểm) — kỳ vọng: 18 passed
.\.venv\Scripts\python.exe -m pytest -q

# Test bonus (legal-KG + 5 extension #0-#4 + crawl) — kỳ vọng: 21 passed
.\.venv\Scripts\python.exe -m pytest bonus -q --override-ini="addopts="
```

> Lưu ý: `pytest.ini` mặc định gom thư mục `tests/`. Lệnh bonus dùng
> `--override-ini="addopts="` để chỉ chạy đúng file bonus, không lẫn 18 test core.

---

## 4. Track dbt (tùy chọn)

```powershell
.\.venv-dbt\Scripts\dbt.exe build --project-dir dbt_project --profiles-dir dbt_project
```

Kỳ vọng: **PASS=11 WARN=0 ERROR=0** (1 seed + 1 view + 1 table + 7 data test + 1 unit test).

---

## Chạy tất cả một lượt (kiểm tra nhanh)

```powershell
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe verify.py
.\.venv\Scripts\python.exe flywheel.py
.\.venv\Scripts\python.exe kg_demo.py
.\.venv\Scripts\python.exe bonus\legal_kg.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest bonus\test_legal_kg.py bonus\test_extensions.py -q --override-ini="addopts="
.\.venv-dbt\Scripts\dbt.exe build --project-dir dbt_project --profiles-dir dbt_project
```

Tất cả xanh = sẵn sàng nộp (xem `rubric.md` mục Submission).
