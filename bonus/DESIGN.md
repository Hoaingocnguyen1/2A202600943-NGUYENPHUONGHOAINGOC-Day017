# Bonus Design — Knowledge graph hỏi-đáp văn bản pháp luật Việt Nam

> Phiên brainstorm theo `BONUS-CHALLENGE.md`. Prototype chạy được kèm theo:
> `bonus/legal_kg.py` (+ `bonus/test_legal_kg.py`). Chạy:
> `python bonus/legal_kg.py` và `python -m pytest bonus -q`.

## Bài toán + ràng buộc thực

**Ai dùng.** Một trợ lý pháp lý cho doanh nghiệp SME và cán bộ pháp chế: hỏi
"xe ô tô tải chạy quá tốc độ 15 km/h trong khu đông dân cư bị phạt bao nhiêu, có
bị tước bằng không?" và nhận câu trả lời **đúng tại thời điểm hành vi xảy ra**,
kèm trích dẫn điều–khoản–điểm.

**Dữ liệu gì.** Kho văn bản quy phạm: Luật, Nghị định, Thông tư — phần lớn là PDF
*scan* (nhiều văn bản cũ không có bản số hoá gốc), bố cục nhiều cột, có bảng biểu,
tiếng Việt có dấu. Cấu trúc lồng: **Điều → Khoản → Điểm**. Đặc thù chí mạng: văn
bản **dẫn chiếu chéo nhau** ("áp dụng mức phạt quy định tại điểm a khoản 5 Điều 5")
và **sửa đổi-bổ sung lẫn nhau** theo thời gian ("được sửa đổi bởi khoản 3 Điều 2
Nghị định 168/2024/NĐ-CP, có hiệu lực 01/01/2025").

**Vì sao khó.** Câu trả lời đúng hiếm khi nằm trong một đoạn văn. Nó là kết quả
của (1) **đi theo chuỗi dẫn chiếu** qua nhiều điều/văn bản, và (2) **chọn đúng
phiên bản còn hiệu lực** tại ngày hành vi. Sai một trong hai → câu trả lời *trông
hợp lý nhưng sai luật* — đúng loại "silent regression" mà VIBE-CODING.md cảnh báo.
`bonus/data/nd_giao_thong_sample.md` cố ý giữ độ bẩn (xuống dòng giữa câu kiểu OCR,
dấu cách thừa, dẫn chiếu lồng nhau) để extractor phải xử lý dữ liệu *khó* như thật.

## Các câu hỏi mở đã chọn (quyết định + đánh đổi)

**1. RAG vector hay knowledge graph? (câu §6)**
*Quyết định:* **Graph cho lớp truy vấn lập luận, vector cho lớp tra cứu literal —
hybrid, không chọn một.* Câu hỏi "mức phạt cho Điều 6 khoản 5" cần nối
`Điều 6 k5 → Điều 5 k5 điểm a`; **không đoạn chunk nào chứa cả hai** (prototype in
ra `single_chunk_answers_it = False`). Vector top-k chỉ trả về *một nửa* chuỗi dù
embedding tốt đến đâu. Graph mã hoá sẵn phép join nên `resolve_chain` đi đúng
đường. *Đánh đổi X vs Y:* graph **đắt khi dựng** (trích triple + entity resolution)
nhưng **rẻ và đúng khi truy vấn**; vector **rẻ khi dựng** nhưng **không bắc được
cầu multi-hop**. Chọn X (graph cho reasoning) vì miền này, đa số câu giá trị cao là
multi-hop.

**2. Trích triple bằng regex tất định hay bằng LLM? (câu §1 + §6)**
*Quyết định:* **LLM `LLMGraphTransformer` cho production; regex chỉ để prototype.**
Prototype regex của tôi đã bắt được dẫn chiếu lồng (`điểm/khoản/Điều`), giải được
"Điều này", và — sau bước **dồn dòng kiểu OCR** (`_logical_lines`) + theo dõi **văn
bản đích của khối "sửa đổi"** — nối đúng `NĐ168:đ2.k1 → NĐ100:đ5.k5.đa` xuyên văn
bản. *Đánh đổi:* regex **tất định, zero-cost, audit được** nhưng **giòn** trước
diễn đạt tự nhiên ("theo quy định của pháp luật về xử lý vi phạm hành chính" —
không có số điều để bắt). LLM **bao phủ rộng** nhưng **tốn token, phi tất định, có
thể bịa cạnh**. Chọn LLM *có entity resolution + người rà soát* cho bản thật, giữ
regex làm baseline kiểm chứng hồi quy.

**3. Point-in-time ở đâu? (câu §5 — train/serve parity)**
*Quyết định:* **ASOF trên `valid_from <= ngày_hành_vi`, không bao giờ "bản mới
nhất".** Đây là quyết định **failure-semantics** quan trọng nhất. Prototype:
vi phạm **2024-06-01** phải áp mức **4–6 triệu (NĐ100/2019)**, không phải 6–8 triệu
(NĐ168/2024 hiệu lực 2025). Trả "bản mới nhất" = **áp dụng hồi tố mức phạt nặng
hơn**, trái nguyên tắc không hồi tố (tinh thần Điều 156 Luật Ban hành VBQPPL) →
công dân bị phạt oan. *Đánh đổi:* ASOF cần một **bảng hiệu lực được con người
curate** (`hieu_luc.csv`) — không tin regex cho ngày hiệu lực; rẻ hơn nhiều so với
chi phí pháp lý của một câu trả lời sai.

**4. Cái gì vỡ khi scale & ai trả tiền? (câu §3 + §9)**
*Quyết định:* **Dựng graph một lần theo batch (incremental theo content-hash), chi
phí LLM extraction là 80% hoá đơn → cắt bằng cache theo hash điều khoản.** Ở 100×
văn bản, bottleneck không phải truy vấn (graph traversal rẻ) mà là **re-extract
toàn bộ mỗi lần một văn bản đổi**. Chỉ re-embed/re-extract điều khoản có content
hash thay đổi (giống ext. #1 của lab). *Đánh đổi:* cache phức tạp hơn nhưng cắt
~90% chi phí LLM định kỳ.

## Phương án bị loại (kèm lý do)

- **Chỉ dùng vector RAG flat + chunk lớn.** Bị loại: prototype chứng minh chuỗi dẫn
  chiếu nằm rải ở các điều khác nhau; top-k không bao giờ trả đủ chuỗi → sai một
  cách *âm thầm*. Tăng `k` chỉ thêm nhiễu, không thêm cầu nối.
- **Trích triple thuần regex cho production.** Bị loại: chính prototype cho thấy
  giới hạn — dẫn chiếu kiểu "theo quy định của pháp luật về…" (không có số điều)
  hoặc bảng biểu scan lệch cột thì regex bó tay; cần LLM + người rà soát.
- **Giả định "luật mới nhất luôn đúng".** Bị loại vì lý do failure-semantics ở §3:
  sai về mặt pháp lý cho mọi hành vi xảy ra trước ngày sửa đổi.

## Sơ đồ kiến trúc

```
PDF scan (Luật/NĐ/TT)
   │  OCR + de-wrap dòng (_logical_lines)        ◀── bước làm sạch kiểu §10 (tiếng Việt scan)
   ▼
Bronze: văn bản thô (append-only, giữ nguyên)
   │  trích cấu trúc Điều→Khoản→Điểm  +  trích dẫn chiếu/sửa đổi (LLM ⟂ regex baseline)
   ▼
Triples (src, DẪN_CHIẾU/SỬA_ĐỔI, dst)  ──► Knowledge Graph (đa văn bản)
   │                                                      │
   │  bảng HIỆU LỰC (con người curate, CSV)               │ resolve_chain: multi-hop
   ▼                                                      ▼
ASOF point-in-time (valid_from ≤ ngày hành vi)   ◀── join ── Câu trả lời + trích dẫn điều-khoản
                                                            (đúng phiên bản, đúng thời điểm)
```

## Bối cảnh Việt Nam (câu §10)

Ba điều khác hẳn một bài blog tiếng Anh: (a) **tiếng Việt có dấu trên bản scan** →
OCR sai dấu làm hỏng cả entity resolution lẫn full-text search, nên bước de-wrap +
chuẩn hoá Unicode là bắt buộc, không phải tuỳ chọn; (b) **hệ thống dẫn chiếu/sửa
đổi-bổ sung dày đặc** của VBQPPL Việt Nam khiến graph + point-in-time là *cốt lõi*,
không phải bonus; (c) **PDPL (Luật 91/2025)** — nếu mở rộng sang bệnh án/hợp đồng
có dữ liệu cá nhân thì khâu quarantine/DLQ phải kèm tách PII trước khi vào model,
một ràng buộc vận hành thật mà bản tiếng Anh thường bỏ qua.
