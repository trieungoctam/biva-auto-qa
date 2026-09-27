# auto-qa — Tổng hợp hiện trạng (đóng gói để brainstorm vòng sau)

> Ngày: 27/09/2026 · Người chốt: owner (trieungoctam) · Trạng thái: sản phẩm nội bộ đang chạy thật với 2 bot
> Cách dùng tài liệu này: đọc mục 1-4 cho bối cảnh, mục 5-7 cho "đang có gì", mục 8-9 cho "còn thiếu gì", mục 10 là agenda gợi ý cho buổi brainstorm kế tiếp.

## 1. Sản phẩm là gì

**auto-qa** — công cụ QA callbot nội bộ cho team: kịch bản là dữ liệu (YAML) →
chạy vào bot thật qua SSE chat → chấm lớp protocol (deterministic) → xuất
transcript + báo cáo → **người** review chất lượng nghiệp vụ trên transcript
(không LLM judge). LLM duy nhất một vai: caller đóng vai khách sinh lời thoại.
Triết lý xuyên suốt: *kịch bản là dữ liệu, tài liệu là chân lý, review là việc người.*

## 2. Hành trình (các mốc đã làm)

| Thời điểm | Mốc |
|---|---|
| Khởi đầu | Dọn dedựng: bỏ webapp cũ/judge/MCP; LLM chỉ còn caller |
| Kiến trúc bots/ | `bots/<bot>/` phân biệt raw (local, gitignore) ↔ knowledge (đã xử lý) ↔ situations (mix được) ↔ scenarios |
| Bot futa | Xử lý 114 cuộc gọi thật + bộ docs nghiệp vụ `nghiep-vu-futa-dl-mdm` → rubric chuẩn (nhãn tin cậy); target bot test 8292 |
| Chạy thật | 5/5 kịch bản PASS protocol; review transcript phát hiện 4 lỗi bot thật (lọt đơn 5 vé, đọc SĐT, loop giờ, xử lý chuyến 404) |
| Web UI v1 | Chạy/Lịch sử/Bot/Admin; users key băm; queue FIFO; review verdict + neo lượt T#; calls N/kịch bản; INDEX.md tự ghi conv ID |
| Sản phẩm hoá | PRD/TECH-DESIGN/RUNBOOK/USER-GUIDE; 4 quyết định chốt (no-notify, gộp M1+M2, UI admin quản người, issue ngoài tool) |
| Cloud-first | VPS là nguồn chân; editor nghiệp vụ từ UI + git audit từng sửa |
| Supabase | Project riêng `auto-qa` (Singapore); bảng `aq_*`; đã migrate toàn bộ dữ liệu; webui/CLI đọc ghi DB |
| Hiện tại | Owner phản hồi: **UX/UI + cách hoạt động chưa đúng hướng** → có bản thảo `docs/REDESIGN-v2.md` chờ duyệt |

## 3. Kiến trúc hiện tại

```
CLI (autoqa run/ui/db-migrate)          Web UI (FastAPI + static JS)
        │                                        │  auth key (users) · queue FIFO 1 worker
        ▼                                        ▼
┌────────────────────────── engine (ổn, giữ nguyên) ──────────────────────────┐
│ runner: script-mode | llm-mode (caller LLM sinh thoại theo goal/persona)     │
│ adapter SSE chat (init + /chat/stream) → bot thật                            │
│ oracle protocol: reply_nonempty · tag · forbidden_phrase · endcall sớm       │
└──────────────────────────────────────────────────────────────────────────────┘
        │ rows (call i/N, transcript)                │ events? (chưa có — điểm cải tạo)
        ▼                                           ▼
   báo cáo MD + INDEX.md                     Supabase aq_* (nguồn chân)
```

- **bots/<bot>/**: `raw/` (gốc, chỉ local) → `knowledge/business.md` (rubric) +
  `call-scripts/` (văn phong caller) · `situations/` (module mix) · `scenarios/`
  · `profile.yaml`. Kịch bản mix tình huống qua `mix: [a, b]` (goal nối, luật
  gộp, câu cấm hợp nhất, max_turns cộng extra_turns).
- **Danh tính**: `aq_users` (key SHA-256, role admin/member), admin bootstrap qua
  env một lần; mọi hành động gắn tên (run, review, sửa nghiệp vụ).
- **Sửa nghiệp vụ**: editor YAML/markdown validate bằng chính loader; ghi
  Supabase trước → file → `git commit` author theo người UI (audit + revert).

## 4. Dữ liệu — ở đâu, ai sở hữu

| Dữ liệu | Nơi sống | Ghi chú |
|---|---|---|
| users, schedules, runs/calls (transcript jsonb), reviews, knowledge, scenarios, situations | **Supabase** `aq_*` | nguồn chân; table editor Supabase sửa được (áp sau restart) |
| bots/ file + git | bản làm việc (hydrate từ DB lúc boot) | git = audit lịch sử sửa |
| runs/*.jsonl, INDEX.md, *.md | artifact song song | CLI local mode |
| `bots/*/raw/` | **chỉ local** | PII/tài liệu gốc — không lên cloud bao giờ |
| config.yaml (targets whitelist) | git + deploy | không sửa từ UI (chống bắn nhầm host) |

## 5. Tính năng đang có (checklist)

- [x] CLI: `run` (--suite/--target/--calls/--user), `ui`, `db-migrate`
- [x] Web: Chạy test (chọn bot/kịch bản/target/calls, cảnh báo GĐ-01) · Lịch sử
      (nhóm theo run, filter, export MD/CSV) · Dashboard (pass-rate bar, issue,
      review-rate) · Bot (đọc rubric + admin sửa) · Admin (users, xoay key)
- [x] Review: verdict ok/issue/warn + reviewer + neo lượt T# + note; nhiều người
      review song song một call
- [x] calls N/kịch bản (persona phone đổi suffix né cache bot); report "PASS 3/5"
- [x] Scheduler in-proc (schedules.yaml / aq_schedules, marker chống chạy lại)
- [x] Queue FIFO + vị trí hàng đợi (không 409)
- [x] Git audit mọi sửa từ UI; CRUD kịch bản/tình huống có template
- [x] Supabase backend + FakeDb test; test cách ly khỏi DB thật (autouse)
- [x] 69 test pass; deploy Docker compose (VPS) + RUNBOOK

## 6. Nhật ký quyết định đã chốt

1. Không LLM trong review — người đọc transcript chấm (nguyên tắc nền).
2. Notification (Slack/Telegram): **backlog**, không làm.
3. Nhịp: gộp M1+M2 một đợt; M3 (CRUD) đã kéo lên làm sớm theo yêu cầu cloud.
4. Người dùng: UI admin quản lý (không env keys).
5. Vòng đời issue (mở→đã sửa): ngoài tool (Linear/sheet).
6. Cloud-first → sau đó **Supabase** thay file làm nguồn chân (raw/ vẫn local).
7. Kiến trúc kịch bản: situations mix được; profile tự kế thừa khi nằm dưới
   `bots/<bot>/`; QA chấm bot theo **giả định** trong docs, không theo lý tưởng.

## 7. Kết quả chạy thật đáng nhớ (bot futa 8292)

- 5/5 kịch bản PASS protocol; smoke phản hồi đúng rubric từ T0.
- 4 phát hiện lỗi bot (đã review tay): lọt đơn **5 vé** qua prompt (QĐ-03 vi
  phạm — nghiêm trọng nhất); đọc chữ số SĐT (QĐ-16); **loop 5 lượt** hỏi lại
  "mấy giờ" không hiểu mốc ước lượng; gặp chuyến 404 thì **bỏ cuộc** thay vì gợi
  chuyến gần (GĐ-19).
- Rủi ro ghi nhận: 2 conversation kết thúc bằng "thông tin đúng rồi" của khách
  → có thể đã tạo vé thật trên DEV (GĐ-01, không API hủy) — kịch bản sau đó
  thiết kế dừng trước lời đồng ý.

## 8. Đang bỏ ngỏ / chưa làm

- **Redesign v2** (bản thảo `docs/REDESIGN-v2.md`): Run Room realtime, review
  trong chat, lịch sử theo conversation — CHƯA duyệt, CHƯA làm.
- Auto booking: thiết kế 3 lớp khoá đã chốt nhưng chờ API đọc kết quả booking
  từ team bot + luồng dọn vé test.
- Export tuần cho lead; trang "vé test cần hủy" (phần đuôi M3).
- Bot mới vẫn tạo bằng tay theo TEMPLATE (không có flow onboarding bot).
- Verify đóng gói Docker image trên VPS thật (mới chạy local; compose đã sẵn).

## 9. Phản hồi mới nhất của owner (nguồn cho redesign)

- UX/UI **không đúng hướng muốn**; cả **cách hoạt động** không đúng.
- **Luồng chat SSE (engine) là ổn** — giữ nguyên.
- Đã chốt qua hỏi nhanh: vẫn **test-first** · không chat tay · **review trong
  chat** · "sai" gồm cả: muốn thấy chat chạy ngay + IA trục conversation + thẩm
  mỹ chưa ra product.
- 3 câu mở chưa trả lời: nút Dừng run? hiển thị giữa chừng bot trả lời?
  link chia sẻ Run Room chỉ-đọc?

## 10. Agenda gợi ý cho buổi brainstorm tới

1. Duyệt/đập `docs/REDESIGN-v2.md` (Run Room 3 cột, luồng Chạy→Room ngay).
2. Trả lời 3 câu mở ở mục 9.
3. Quyết định phạm vi đợt redesign (6 bước trong REDESIGN-v2 mục 7) — cắt gì trước nếu gấp.
4. Xem xét lại: có nên tách "xem live" cho người non-QA (PM xem bot chạy) không.
5. Đề xuất mới (nếu có): onboarding bot mới, thông báo, auto booking phase.

## Phụ lục — bản đồ tài liệu & mã

| Tài liệu | Nội dung |
|---|---|
| `docs/PRD.md` | personas, milestone, metrics, quyết định |
| `docs/TECH-DESIGN.md` | kiến trúc kỹ thuật + tradeoffs (Supabase, queue, scheduler, CRUD) |
| `docs/RUNBOOK.md` | deploy/backup/xoay key/Supabase/sự cố |
| `docs/USER-GUIDE.md` | hướng dẫn member (chạy, review chuẩn) |
| `docs/REDESIGN-v2.md` | bản thảo redesign (chờ duyệt) |
| `bots/TEMPLATE-bot.md` | hợp đồng raw↔knowledge + checklist tiếp nhận bot |
| `supabase/migrations/` | schema `aq_*` |
| Repo | github.com/trieungoctam/biva-auto-qa (private) · tests: 69 · bots: futa (8292), live-demo |
