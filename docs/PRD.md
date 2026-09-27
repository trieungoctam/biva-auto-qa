# PRD — auto-qa: sản phẩm nội bộ QA callbot

> Trạng thái: DỰ THẢO để chốt với team · Ngày: 2026-09-27 · Owner: trieungoctam
> MVP (M0) đã chạy thật: CLI + web UI 3 màn, 2 bot (futa 8292, live-demo), INDEX.md, Docker deploy.

## 1. Bối cảnh & vấn đề

Team đang QA callbot bằng tay: gọi thử, đọc transcript, ghi chú rải rác. MVP auto-qa
đã tự hoá phần chạy (kịch bản YAML → bot thật → transcript + báo cáo), nhưng là công
cụ của một người: một API key chung vô danh, chạy chồng nhau bị từ chối, kết quả
không có dòng chảy chất lượng, không quy trình ai-làm-gì.

## 2. Mục tiêu

- Mọi thành viên team tự chạy test và tự review mà **không cần ai hướng dẫn lại**.
- Mọi kết quả test đều **có danh tính** (ai chạy, ai review) và **tra cứu được** theo conversation ID.
- Chất lượng bot nhìn được **theo thời gian** (trend) thay vì từng run rời rạc.
- Regression chạy **tự động theo lịch**, người chỉ đọc kết quả.

## 3. Người dùng

| Persona | Tần suất | Việc chính |
|---|---|---|
| QA runner | hằng ngày | chọn bot + kịch bản + số calls → chạy → xem kết quả/conv ID |
| Reviewer | hằng ngày | lọc "chưa review" → đọc transcript đối chiếu rubric → verdict + neo theo lượt |
| Prompt engineer | khi có issue | đọc issue aggregate → sửa kịch bản/knowledge (CRUD, git audit) → verify |
| Lead/PM | tuần | dashboard trend, export báo cáo |

## 4. Hành vi chính (jobs-to-be-done)

1. "Chạy lại regression của futa sau khi team prompt sửa bot" — chọn suite, N calls, chạy, so với lần trước.
2. "Tôi là Lan, duyệt 20 transcript hôm nay" — filter chưa review, chấm verdict, neo finding tại đúng lượt sai.
3. "Kịch bản nào hay đỏ nhất 2 tuần nay?" — trend theo kịch bản/bot, đếm cả verdict issue của người review.
4. "Sáng mai tự động chạy smoke mọi bot, có gì đỏ thì báo nhóm" — schedule + notification.
5. "Sửa max_turns của kịch bản này ngay từ UI" — CRUD + tự commit git để có audit/rollback.

## 5. Phạm vi theo milestone

### M1 — Nhiều người dùng được (gộp với M2 thành một đợt v1)
- **Quản lý người dùng bằng UI admin** (`users.yaml`: tên + key đã băm, vai trò admin/member; admin đầu bootstrap qua `AUTOQA_ADMIN_KEY` một lần) — tên hiện khắp UI, gắn vào INDEX + review.
- Hàng đợi FIFO thay vì 409; hiển thị vị trí chờ.
- Review verdict (ok/issue/warn) + reviewer + **neo theo lượt T#** + note → `runs/<id>.review.yaml`.
- `calls` (N conversations/kịch bản, persona phone tự đổi suffix) + cột call i/N.
- Lịch sử: filter theo bot / người review / chưa review / có issue.
- Export MD/CSV một run (kèm review) để gửi team.

### M2 — Tự chạy được (làm cùng đợt với M1)
- Schedule: `schedules.yaml` (bot + suite + giờ + calls) → service cron trong compose; kết quả vào INDEX như run thường.
- Dashboard: pass-rate theo kịch bản/bot theo tuần; top kịch bản đỏ; tỉ lệ đã review.
- Notification outbound webhook (Slack/Telegram): **BACKLOG** theo quyết định 2026-09-27 —
  không làm đợt này; thiết kế giữ ở TECH-DESIGN mục 3.2.

### M3 — Tự chủ nghiệp vụ
- CRUD kịch bản + situations từ UI (validate qua `load_scenario`, rollback khi lỗi); server mount `bots/` rw + **tự git commit mỗi sửa** (audit + rollback).
- Báo cáo định kỳ export (tuần) cho lead.
- Quy trình "vé test cần hủy" (chuẩn bị cho auto booking): danh sách theo dõi + nhắc TĐV.

## 6. Metrics

- % kịch bản chạy trong tuần **được review** (target > 80%).
- Thời gian từ run xong → review xong (target < 24h).
- Số issue verdict/tuần và số issue đóng (sau khi sửa prompt) — trend đi xuống.
- Số run tự động (scheduled) / tổng run — mức độ tự hoá.

## 7. Rủi ro & đối sách

| Rủi ro | Đối sách |
|---|---|
| Auto booking tạo vé thật DEV, không hủy được | 3 lớp khoá (env + `booking: true` + confirm riêng); rate limit 1/bot/ngày; trang theo dõi vé cần hủy — chỉ làm khi có API đọc kết quả booking |
| Chi phí LLM khi N calls × nhiều người | ước lượng hiển thị trước chạy; cap calls/run theo env; metric số LLM call |
| `runs/` là dữ liệu sản phẩm mất là mất review | backup hằng đêm (RUNBOOK); INDEX + review yaml trong rsync |
| Sửa kịch bản từ UI làm hỏng suite | validate bằng chính loader; git commit từng sửa → rollback 1 lệnh |
| PII trong transcript bot | tool nội bộ + key theo người + backup trong hạ tầng team |

## 8. Quyết định đã chốt (2026-09-27)

1. Notification: **chưa cần** — M2 chỉ schedule + dashboard; outbound webhook để
   backlog (thiết kế sẵn ở TECH-DESIGN, bật khi team muốn).
2. Nhịp triển khai: **gộp M1+M2 làm một đợt v1** — M3 (CRUD/export đầy đủ) sau khi
   v1 chạy thật.
3. Người dùng: **UI admin quản lý** (thêm/xoá người, xoay key ngay trên UI, store
   `users.yaml` chứa key đã băm) — không dùng env keys.
4. Vòng đời issue (mở → đã sửa): **ngoài tool** (Linear/sheet) — tool chỉ lưu verdict
   + người review; trend issue đọc từ verdict khi cần.
