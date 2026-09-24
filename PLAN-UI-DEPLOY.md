# Plan — Giao diện & Deploy auto-qa cho người khác dùng

> Trạng thái: ĐÃ CHỐT — VPS Docker · 1 API key chung · P1 = đọc/chạy (không sửa từ UI).

## 1. Mục tiêu & nguyên tắc

Người không chạy terminal (QA, PM, ops) dùng được auto-qa: chọn bot → chọn kịch bản
→ chạy test vào bot thật → đọc transcript → tự review và tra conversation ID.
Deploy MỘT chỗ, nhiều người dùng qua trình duyệt.

Nguyên tắc (giữ nguyên kiến trúc đã dựng):

- UI là **lớp mỏng** gọi thẳng các hàm core hiện có (`load_suite`, `run_suite`,
  `write_report`, `_append_index`) — không đẻ logic nghiệp vụ thứ hai trong web layer.
- **Không đưa LLM vào review** — UI chỉ hiển thị transcript + ô ghi chú người đọc.
- `bots/*/raw/` **không bao giờ** lộ qua API/UI (chỉ knowledge + scenarios).
- Whitelist target giữ trong `config.yaml`; UI chỉ chọn target theo TÊN, không sửa URL
  (chống bắn nhầm host, chống chạm đường booking).

## 2. Phạm vi UI (MVP)

4 màn hình, pattern FastAPI + static/ JS thuần (giữ đúng pattern webui cũ từng có
trong repo — không node, không build tool; resurrect phần run/history, bỏ judge/review cũ):

| Màn | Nội dung | API |
|---|---|---|
| Chạy test | Chọn bot (từ `bots/`), multi-select kịch bản, target override, concurrency → chạy nền, progress + kết quả PASS/FAIL/BLOCKED kèm conv ID | `GET /api/bots`, `GET /api/bots/{b}/scenarios`, `POST /api/runs`, `GET /api/runs/{id}/status` |
| Lịch sử | Bảng từ `runs/INDEX.md` (run, target, kịch bản, trạng thái, conv, báo cáo) → mở run chi tiết | `GET /api/runs` |
| Chi tiết run | Transcript từng kịch bản dạng chat (Khách/Bot, tag \|CHAT/\|ENDCALL, caller_note), checks FAIL, tải JSONL/MD | `GET /api/runs/{id}` |
| Review | Ô ghi chú tay cho từng kịch bản, lưu `runs/<id>.notes.yaml`; nút "đã duyệt" (chỉ đánh dấu, không đổi status tự động) | `POST /api/runs/{id}/notes` |

Read-only có sẵn: cây `bots/<bot>/` (profile, knowledge/business.md, situations) —
hiển thị để người review đối chiếu rubric. **Sửa kịch bản/config từ UI để phase sau.**

Ràng buộc vận hành trong MVP:
- MỘT run chạy cùng lúc (lock toàn cục); hàng đợi từ chối kèm thông báo.
- Cảnh báo trước khi chạy kịch bản `mode: llm` của bot có ghi chú GĐ-01 trong
  knowledge (FUTA DEV tạo vé thật khi khách đồng ý bản xác nhận) — hiển thị block
  cảnh báo lấy từ mục "CẢNH BÁO KHI CHẠY TEST" của business.md.
- Auth: 1 API key chung (`AUTOQA_UI_KEY`, header `X-API-Key`) — đủ cho team nội bộ.

## 3. Deploy

```
[Docker] python:3.12-slim
  pip install -e '.[ui]'      # fastapi + uvicorn
  uvicorn autoqa.webui:app --host 0.0.0.0 --port 8788
volume mount: ./bots (ro: knowledge/scenarios; raw bị chặn ở app layer),
              ./runs (rw), ./config.yaml, .env (secrets, không vào image)
```

- `docker compose up -d` — chạy được ở cả máy nội bộ (LAN) lẫn VPS.
- Secrets (GEMINI_API_KEY, token target) chỉ qua env; UI không bao giờ trả về giá trị.
- Backup = git (bots/, config) + rsync thư mục runs/ (INDEX.md là lịch sử chân).
- HTTPS: reverse proxy (caddy/nginx) nếu exposure ngoài LAN.

## 4. Phase

| Phase | Việc | Kết quả nghiệm thu |
|---|---|---|
| P1 | `autoqa/webui.py` (app + job runner + API trên) + `static/` 4 màn | Chạy được suite futa từ trình duyệt, thấy conv ID + transcript |
| P2 | Review notes + export (tải MD/JSONL, lọc theo bot/status) | Người review ghi chú được, note sống sót qua restart |
| P3 | Sửa kịch bản/profile từ UI (validate + rollback — resurrect pattern `ops.py` cũ) + thêm bot mới bằng form | Đổi goal/max_turns từ UI, không vỡ YAML |
| P4 | Phân quyền nhẹ (nhiều key, ghi ai chạy/ai duyệt vào INDEX) — chỉ nếu cần | Log người dùng trong INDEX.md |

## 5. Rủi ro & đối sách

- **Tạo vé thật trên DEV** khi người dùng bấm chạy kịch bản goal FUTA: cảnh báo
  trên UI + mặc định suite hiển thị nhãn rủi ro lấy từ knowledge; tuỳ chọn env
  `AUTOQA_ALLOW_BOOKING_RISKY=true/false` để khoá chạy llm-suite khi mở cho đông người.
- **Chi phí LLM**: mọi kịch bản llm tốn ~1 call/lượt (gemini flash-lite) — hiện đủ rẻ,
  ghi nhận số lượt/run trong INDEX để theo dõi.
- **Concurrency ẵ CHẠM bot thật**: mặc định concurrency 1-2, không cho vượt 4.
- Ai cũng chạy được = ai cũng tạo conversation trên bot test; chấp nhận được vì
  conversation không phải booking (trừ cảnh báo GĐ-01 ở trên).

## 6. Câu hỏi chốt trước khi implement

1. Host ở đâu: máy nội bộ (LAN/VPN) hay VPS/cloud? (mặc định đề xuất: VPS Docker)
2. Số người dùng + có cần phân quyền không? (mặc định: 1 API key chung)
3. Có cần sửa kịch bản từ UI sớm không, hay P1-P2 đọc/chạy là đủ?
