# Reflection — Day 17 (≤ 200 words)

Answer briefly, in your own words. This is graded on reasoning, not length.

1. **The flywheel.** Day 13 emitted agent traces; today you turned them into an
   eval set and DPO pairs that Day 22 will train on. Which step in
   `traces → Bronze → datasets` would break most silently in production if you
   got it wrong — and how would you detect it?

2. **Decontamination.** Your run dropped 2 of 3 preference pairs because their
   prompts were in the eval set. What concretely goes wrong if you *skip* this
   step and train on those pairs? How would the lie show up in your metrics?

3. **Point-in-time.** The naive join leaked a future `lifetime_spend` into the
   training row. Describe one feature in a system you know that would be
   dangerous to join without an `ASOF`/point-in-time guard.

4. **Graph vs vector.** From `kg_demo.py`, name one question the knowledge graph
   answers well that flat chunk retrieval (`embed.py`) would struggle with, and
   one where the graph is overkill.

_Write your answers below._

> Bản nháp dựa trên kết quả run thật (verify 16/16, pytest 18, flywheel: 21 spans
> → 2 eval, 3 cặp thô → 1 sạch, 2 dòng leaky). Chỉnh lại theo ý mình trước khi nộp.

**1. The flywheel.** Bước dễ hỏng âm thầm nhất là `flatten()` hoisting các thuộc
tính `gen_ai.*` vào cột Bronze (đặc biệt `status` và `split`). Nếu map sai một key,
pipeline **vẫn chạy**, chỉ là eval set / DPO pairs được dựng trên dòng sai — không
exception, không test đỏ. Phát hiện bằng contract trên Bronze spans: assert số
dòng/span, tỉ lệ non-null của `status`/`split`, và một check đếm cứng (verify.py kỳ
vọng 21 spans → 2 eval). Lệch số là tín hiệu sớm nhất.

**2. Decontamination.** Bỏ bước này → 2 cặp có prompt nằm trong eval lọt vào train.
Model **học thuộc** đáp án eval, nên điểm eval tăng *giả* — đo trí nhớ chứ không đo
khả năng tổng quát. Lời nói dối lộ ra khi điểm eval đẹp nhưng holdout mới / hiệu
năng production đứng yên (hoặc tệ đi): khoảng cách eval-vs-thực-tế ngày càng giãn.

**3. Point-in-time.** Trong chấm điểm tín dụng, `tổng_dư_nợ_quá_hạn` của khách:
join "giá trị mới nhất" sẽ rò rỉ các khoản quá hạn *xảy ra sau* thời điểm xét duyệt
vào dòng training → model trông như tiên tri offline, sập khi serve. Phải ASOF theo
ngày ra quyết định.

**4. Graph vs vector.** Graph thắng: "widget ship từ đâu?" (multi-hop
widget→accessory→Hanoi, không chunk nào chứa cả chuỗi). Graph thừa: "gadget bảo
hành bao lâu?" — một fact đơn, vector lấy đúng một chunk là xong; dựng + duyệt graph
chỉ thêm chi phí vô ích.
