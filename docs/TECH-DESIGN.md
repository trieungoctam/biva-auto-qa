# Tech Design — auto-qa product phase (M1 → M3)

> Tiền đề: MVP (M0) đang chạy — FastAPI mỏng trên core CLI, static JS, Docker compose,
> dữ liệu = file (YAML/JSONL/INDEX.md). Tài liệu này mô tả cách tiến hoá KHÔNG đổi
> triết lý: file-first, không DB, git làm audit.

## 1. Nguyên tắc giữ nguyên

- Web layer vẫn là lớp mỏng gọi core (`load_scenario`, `run_suite`, `write_report`,
  `_append_index`) — thêm module mới chỉ khi core thiếu hook.
- Không LLM trong review. Không DB cho tới khi >100k dòng lịch sử (lúc đó thêm
  SQLite read-only mirror từ JSONL, không thay nguồn chân).
- `bots/*/raw/` mãi mãi không qua API/image/backup.

## 2. M1 — Danh tính, hàng đợi, review

### 2.1 Người dùng: store `users.yaml` + UI admin (quyết định 2026-09-27)
```yaml
# users.yaml — mount rw; KHÔNG chứa key thô, chỉ bcrypt/sha256
- name: tam
  key_hash: "..."          # sha256(key)
  role: admin              # admin | member
- name: lan
  key_hash: "..."
  role: member
```
- Header `X-API-Key` → đối chiếu hash → `request.state.user = name, role`.
- API admin (chỉ role admin): `GET/POST/DELETE /api/users` — thêm người (server
  sinh key, hiển thị MỘT lần để gửi cho người dùng), xoay key, xoá người, đổi vai trò.
- Bootstrap: env `AUTOQA_ADMIN_KEY` (dùng một lần đăng nhập đầu, tạo admin đầu tiên
  vào users.yaml rồi gỡ env).
- UI: nhập key → `/api/me` trả `{name, role}`; tab **Admin** hiện với admin.
- Mọi bản ghi mới có `user`: INDEX thêm cột `Người chạy`; review có `reviewer`;
  (M3) git commit `ui(<name>): ...`.

### 2.2 Hàng đợi FIFO thay 409
- `asyncio.Queue` in-process, worker 1 task; POST /api/runs → enqueue, trả `{position}`.
- `GET /api/runs/{id}/status` thêm `queue_position` khi chưa chạy.
- Restart mất hàng: chấp nhận (run ngắn) — ghi rõ trong RUNBOOK.

### 2.3 Review store
`runs/<id>.review.yaml` — append-only qua lock, schema:
```yaml
- scenario: futa/goal-dat-ve-chuan
  call: 1
  reviewer: lan
  verdict: issue            # ok | issue | warn
  anchor: T7                # lượt chat bị vấn đề (không bắt buộc)
  note: bot lặp câu hỏi giờ 5 lần
  ts: 2026-09-27T10:20:00
```
- API: `POST /api/runs/{id}/review`, `GET /api/runs/{id}/review`.
- UI: trong transcript mỗi lượt có nút "neo lượt này"; verdict chọn 1 trong 3.
- Ghi đè: review mới cùng (scenario, call, reviewer) thay bản cũ — một người một
  verdict cho một mục.

### 2.4 N calls mỗi kịch bản
- `run_suite` nhận `calls=N` (mặc định 1): lặp kịch bản N conversation, persona
  phone thêm suffix `-<i>` (né cache 30 ngày của bot), row JSONL/INDEX thêm `call: i/N`.
- Report gom nhóm: `PASS 3/5` — không tự FAIL gộp (tỉ lệ là dữ liệu, không phải phán quyết).
- Env cap: `AUTOQA_MAX_CALLS_PER_RUN=20`.

## 3. M2 — Tự động hoá

### 3.1 Schedule (đã hiện thực: task in-proc trong webui)
```yaml
# schedules.yaml — mount vào container (mẫu: schedules.yaml.example)
- name: futa-nightly-smoke
  bot: futa
  scenarios: ["futa/smoke-hoi-gia-lich", "futa/goal-chieu-nguoc"]
  at: "07:00"          # múi giờ container
  calls: 1
```
- Scheduler là asyncio task trong chính web app (tick 60s), KHÔNG phải service
  compose riêng như phác ban đầu — lợi ích: chạy scheduled run qua CÙNG queue
  FIFO với run của người (không chồng nhau), một artefact deploy duy nhất.
- Chống chạy lại sau restart: marker `runs/.sched-<name>` ghi ngày đã chạy.
- `Người chạy = scheduler` (hoặc `user:` khai trong schedule) trong INDEX.

### 3.2 Notification — BACKLOG (bỏ theo quyết định 2026-09-27, giữ thiết kế)
- `NOTIFY_WEBHOOK_URL` + `NOTIFY_FORMAT=slack|telegram|generic`.
- Trigger: run done (tóm tắt N PASS/M FAIL/B BLOCKED + link), verdict `issue` mới.
- Fail-safe: lỗi notify không làm hỏng run (log + đếm). Bật lại khi team muốn.

### 3.3 Dashboard trend
- Đọc toàn bộ INDEX + review files on-request (93 dòng hiện tại, vài trăm sau này —
  rẻ; cache in-memory 60s).
- API: `GET /api/stats?bot=&days=` → per-scenario pass-rate, issue count, review rate.

## 4. M3 — CRUD + audit

- Mount `bots/` rw; sau mỗi sửa: `git -C /app add <file> && git commit -m "ui(<user>): ..."`
  (container mount cả `.git`; nếu không mount được thì ghi patch vào `audit/` + push khi deploy).
- API CRUD validate bằng `load_scenario` (loader là contract duy nhất); sai → 400,
  file nguyên vẹn (ghi tạm → validate → rename).
- Không CRUD bot mới / không sửa `config.yaml` từ UI (thêm target = việc deploy, có
  whitelist host để bảo vệ).
- Export tuần: `GET /api/export/week?from=` → MD gộp runs + reviews (cho lead).

## 5. Sơ đồ triển khai mục tiêu

```
            ┌─ autoqa-web (uvicorn :8788) ─ queue 1 worker ── core run_suite
VPS docker ─┤                       │
            ├─ autoqa-cron  (schedules.yaml)
            ├─ volumes: runs/ (rw, backup đêm) · bots/ (rw từ M3, git audit)
            │           config.yaml (ro) · .env (keys: UI users, LLM, target token, notify)
            └─ reverse proxy (HTTPS) → team
```

## 6. Bảo mật & dữ liệu

- Key xoay/thêm người: qua UI admin (`/api/users`) — không cần sửa env hay restart.
- Backup `runs/` hằng đêm (rsync/rclone sang máy chủ backup của team) — review verdict
  nằm đây; `bots/` backup bằng git push (repo GitHub private sẵn).
- Không log giá trị key/token; transcript không rời tool trừ export chủ đích.

## 7. Tradeoffs đã chốt

| Phương án | Chọn | Lý do |
|---|---|---|
| DB (Postgres/SQLite) vs file | file + git/INDEX | cỡ dữ liệu nhỏ, audit bằng git, zero-ops |
| User store vs env keys | env keys | không UI admin, không bảng user; đủ tới ~20 người |
| Queue bền (Redis) vs in-proc | in-proc FIFO | run ngắn, mất hàng khi restart chấp nhận |
| Sửa YAML giữ comment | bỏ comment khi UI sửa | tránh thêm dep ruamel; git diff vẫn đọc được |
| Scheduler vs systemd/K8s CronJob | service loop trong compose | một artefact deploy duy nhất |
