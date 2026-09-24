# biva-auto-qa

Bot QA cho callbot: kịch bản là dữ liệu YAML trong `bots/<bot>/`, chạy vào bot thật
qua SSE chat, chấm lớp protocol (deterministic), xuất JSONL + báo cáo markdown.
LLM duy nhất một vai: caller đóng vai khách. Chất lượng nghiệp vụ do người review
trên transcript. Xem `bots/TEMPLATE-bot.md` cho kiến trúc raw/knowledge của từng bot.

## CLI

```bash
pip install -e '.[dev,ui]'
python -m autoqa run --suite 'bots/futa/scenarios/*.yaml' --out runs
# Kết quả: runs/<id>.jsonl + runs/<id>.md; chỉ mục mọi run (kèm conversation ID): runs/INDEX.md
```

## Web UI (cho người không dùng terminal)

```bash
python -m autoqa ui                 # http://127.0.0.1:8788
AUTOQA_UI_KEY=... python -m autoqa ui --host 0.0.0.0   # có auth khi expose
```

Màn hình: Chạy test (chọn bot + kịch bản) · Lịch sử (tra conversation ID từ
`runs/INDEX.md`, xem transcript từng run) · Bot (đọc rubric `knowledge/business.md`).

## Deploy VPS (Docker)

```bash
cp .env.example .env                # điền GEMINI_API_KEY, token target, AUTOQA_UI_KEY
docker compose up -d --build        # → http://<vps>:8788
```

- `runs/` mount rw (lịch sử sống sót qua rebuild), `bots/` + `config.yaml` mount ro.
- `bots/*/raw/` không bao giờ vào image (`.dockerignore`) và không có API nào serve.
- Secrets chỉ qua env; UI không trả về giá trị key/token.
- Chi tiết phạm vi các phase: `PLAN-UI-DEPLOY.md`.

## Test

```bash
pytest tests/ -q
```
