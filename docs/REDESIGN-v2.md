# Redesign v2 — auto-qa: "phòng chạy test trực tiếp"

> Ngày: 27/09/2026 · Trạng thái: ĐÃ CHỐT HƯỚNG (brainstorm với owner), chờ duyệt chi tiết
> Nguyên tắc đọc: mục 1-2 là cam kết; mục 4-5 là thiết kế; mục 7 là việc cần làm.

## 1. Chẩn đoán — vì sao bản hiện tại "không đúng hướng"

| Triệu chứng người dùng nêu | Gốc rễ |
|---|---|
| "Muốn bấm chạy là thấy chat chạy ngay" | Hiện tại: bấm chạy → progress bar poll `x/N` → xong phải tự sang tab Lịch sử moi run ra. Trải nghiệm tách rời khỏi bản chất sản phẩm: **xem bot nói chuyện**. |
| "IA sai trục — mọi thứ nên xoay quanh conversation" | Đơn vị hiển thị chính là *run* (bảng INDEX, dòng jsonl), trong khi đối tượng tư duy của người QA là *một cuộc gọi*. |
| "Trông như công cụ kỹ thuật" | Bảng dày, chữ_mono_ khắp nơi, không hierarchy; thiếu nhịp thị giác của product (như Linear/Supabase studio), thiếu trạng thái sống (live, streaming). |

Giữ nguyên (được xác nhận ổn): **luồng chat SSE với bot** (engine), mô hình test-first
(chọn kịch bản → chạy → kết quả), caller LLM tự nói (không chat tay), review =
người chấm verdict + neo lượt, Supabase làm backend, users/admin.

## 2. Định hướng sản phẩm (cam kết)

1. **Đơn vị trung tâm = conversation.** Mọi màn hình liệt kê/tra cứu xoay quanh
   cuộc gọi (bot · kịch bản · người chạy · trạng thái · verdict · conv ID).
2. **Chạy test = mở phòng chạy trực tiếp.** Bấm "Chạy" → chuyển sang màn
   *Run Room* ngay: transcript các cuộc gọi hiện dần **từng lượt như đang gọi**,
   không có bước "chờ tiến trình" trung gian.
3. **Review trong chat.** Chấm ok/issue/warn + neo lượt ngay tại dòng lượt thoại
   đang nhìn — live hoặc mở lại từ lịch sử, cùng một giao diện.
4. **Ba luồng thôi:** Chạy · Lịch sử (conversations) · Dashboard. (Bot-rubric và
   Admin là màn phụ nhét vào hợp lý hơn.)

## 3. Kiến trúc thông tin & màn hình

### 3.1 Tab **Chạy** (điểm vào)
```
┌───────────────────────────────────────────────────────────────┐
│  [Chọn bot ▾ FUTA]        [Chạy 3 kịch bản đã chọn  ▶]        │
│  ────────────────────────────────────────────────────────────  │
│  ☑ smoke-hoi-gia-lich   script · 3 lượt                        │
│  ☑ goal-dat-ve-chuan    llm · 16 lượt                          │
│  ☐ goal-chieu-nguoc     llm · 12 lượt          [chọn tất cả]  │
│  Calls/kịch bản [2]  Song song [1]                             │
└───────────────────────────────────────────────────────────────┘
```
- Chọn xong bấm ▶ → **chuyển màn sang Run Room ngay** (không modal tiến trình).
- Ghi nhớ lựa chọn theo bot (đã có). Cảnh báo GĐ-01 hiển thị như hiện tại.

### 3.2 **Run Room** — trái tim của redesign
```
┌────────────┬───────────────────────────────────┬──────────────┐
│ CALLS 3/6  │  goal-dat-ve-chuan · call 2/3     │ RUBRIC       │
│ ● running  │  ───────────────────────────────  │ (business.md │
│ ○ waiting  │  Khách  T0  Dạ em chào em, mình    │  của bot,    │
│ ✓ pass 1/3 │          cho chị đặt vé…           │  collapse    │
│ ✗ fail     │  Bot    T0  Dạ chị đi từ Đà Lạt    │  theo mục)   │
│            │          về Miền Đông Mới…  ▮      │              │
│ [call kế]  │  Khách  T1  …                     │ CHECKS       │
│            │  (streaming từng lượt)            │ ✓ reply_non- │
│            │                                    │ ✗ forbidden  │
│            │  ── khi call kết thúc ──           │ REVIEW       │
│            │  [PASS] [checks] [conv: abc123 ⧉] │ ○ok ○issue   │
│            │                                    │ ○warn + note │
└────────────┴───────────────────────────────────┴──────────────┘
```
- Cột trái: từng call là một mục; trạng thái sống (đang nói, chờ, pass, fail);
  click để xem call khác đang chạy song song.
- Giữa: transcript **live** — lượt khách/bot xuất hiện lần lượt (server đẩy sự
  kiện từng lượt, không poll); caret nhấp nháy khi đang chờ bot; khi hết call
  hiện badge kết quả + conv ID (copy một chạm).
- Phải: rubric đối chiếu (người review cần nhìn song song), checks của call đang
  xem, form review gắn với call đó.
- Thoát giữa chừng: run vẫn chạy nốt nền; quay lại từ Lịch sử.

### 3.3 Tab **Lịch sử** = conversations
- List thẻ conversation (không phải bảng): mỗi thẻ = bot, kịch bản (call i/N),
  ai chạy, bao giờ, chấm protocol, verdict review (nếu có).
- Filter: bot / người / chưa review / issue; bấm thẻ → **mở lại đúng Run Room**
  (chỉ-đọc + review tiếp được) — cùng một giao diện với live.

### 3.4 Tab **Dashboard** (giữ, hạ cấp)
Pass-rate bar + issue trend như hiện tại; bấm dòng → lọc Lịch sử tương ứng.

### 3.5 Phụ
- **Rubric/Bot** & **Admin**: gộp vào menu ⚙ (màn thứ cấp); nội dung như hiện tại.

## 4. Thiết kế thị giác (định hướng)

- Cảm giác: công cụ vận hành tinh gọn kiểu Linear/Supabase studio — tối, một
  màu nhấn (xanh dương nhạt hiện có), nhiều khoảng thở hơn, chữ số tabular.
- Typography: 13-13.5px nền tảng; tiêu đề màn 15px/600; mono **chỉ** dùng cho
  conv ID/YAML — lời thoại là chữ thường dễ đọc.
- Transcript = chat bubbles hai phe (khách trái nền xanh đậm, bot phải), số lượt
  T# dạng mốc mờ; neo review (⌖) hiện khi hover lượt.
- Trạng thái sống: dot nhấp nháy khi đang streaming; skeleton 3 dòng khi chờ
  lượt đầu; transition 200ms mọi tương tác.
- Mật độ: một màn một việc chính — Run Room không có bảng nào.

## 5. Thay đổi cách hoạt động (kỹ thuật)

### 5.1 Realtime từng lượt — event bus trong webui
- `run_suite` thêm callback `on_event(event)` phát tại: `user_say`, `bot_reply`
  (kèm tag), `call_done` (kèm checks/status), `run_done`. Core engine giữ nguyên,
  chỉ thêm mỏng.
- Webui job publish vào **pub/sub in-process** (dict run_id → set[asyncio.Queue]);
  endpoint `GET /api/runs/{id}/stream` (SSE) subscribe, đổ event ra.
- Mở giữa chừng / reload: client gọi detail (DB) vẽ phần đã có rồi mới nghe
  stream — không bỏ sót.
- Nhiều tab cùng xem một run: mỗi tab một queue, ok.

### 5.2 Dữ liệu — không đổi schema
`aq_runs/aq_calls/aq_reviews` đủ dùng (transcript jsonb đã có). Event là
*trạng thái bay*, không lưu. Run Room đọc đầu cuối từ DB như hiện tại.

### 5.3 Queue
Vẫn FIFO 1-worker (an toàn cho bot thật). Cảm giác "chạy ngay" đạt bằng: bấm →
vào Run Room即刻, nếu đang xếp hàng thì panel trái hiện "đang chờ run trước"
thay vì chặn màn hình.

## 6. Những gì KHÔNG đổi

Engine SSE chat + caller; protocol checks; review verdict/anchor/người review;
Supabase (aq_*); users/admin; schedules; CRUD nghiệp vụ + git audit; raw/ local.

## 7. Kế hoạch triển khai (đợt redesign)

| # | Việc | Note |
|---|---|---|
| 1 | `on_event` trong runner + SSE endpoint + pub/sub | nền tảng realtime |
| 2 | Run Room (3 cột, live transcript, review trong chat) | màn lớn nhất |
| 3 | Tab Chạy mới (chuyển màn sang Run Room) | xoá poll UX |
| 4 | Lịch sử conversations + mở lại Run Room | thay bảng INDEX-view |
| 5 | design system dọn (màu/nhịp/bubbles) | theo mục 4 |
| 6 | Dashboard/Bot/Admin vào menu phụ | dọn nav |

## 8. Câu hỏi còn mở (trả lời trước khi làm #2)

1. Run Room có cần nút **DỪNG run** giữa chừng không (hủy các call chưa chạy)?
2. Hiện từng lượt bot trả lời có thể mất 5-20s (SSE dài) — giữa chừng hiển thị
   gì? (đề xuất: "bot đang trả lời…" + spinner nhỏ)
3. Có cần share link Run Room cho người khác xem (không cần key, chỉ đọc)?
   (đề xuất: chưa — nội bộ đã có key)
