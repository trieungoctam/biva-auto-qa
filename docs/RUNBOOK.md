# RUNBOOK — vận hành auto-qa (internal)

> **Cloud là nguồn chân của dữ liệu** (knowledge, kịch bản, tình huống, runs,
> review, users). Admin sửa nghiệp vụ trực tiếp trên UI — mỗi lần sửa server
> tự `git commit` (ai sửa, sửa gì) vào repo trên VPS; kéo về máy bằng
> `git pull`, backup bằng `git push`. Riêng `bots/*/raw/` CHỈ ở máy local
> (PII/tài liệu gốc), không bao giờ lên cloud.

> Ai giữ: owner + 1 backup person. Mọi lệnh chạy trên VPS, trong thư mục repo.

## Deploy lần đầu

```bash
git clone git@github.com:trieungoctam/biva-auto-qa.git && cd biva-auto-qa
cp .env.example .env   # điền: GEMINI_API_KEY, AUTOQA_LIVE_DEMO_TOKEN,
                       # AUTOQA_ADMIN_KEY (dùng 1 lần tạo admin đầu, rồi gỡ)
touch users.yaml schedules.yaml && docker compose up -d --build
curl -s localhost:8788/api/bots -H "X-API-Key: <key>"   # kiểm tra sống
```

HTTPS: đặt caddy/nginx trỏ `:8788`; KHÔNG expose port trực tiếp ra internet nếu
không có TLS.

## Nâng cấp phiên bản

```bash
git pull && docker compose up -d --build
```
- Image rebuild không mất `runs/` (volume). Queue đang chờ mất khi restart — chạy lại.
- Sau nâng cấp có CRUD (M3): `git -C . log --oneline -20` xem sửa từ UI còn nguyên.

## Backup / khôi phục

- `runs/` (INDEX + JSONL + review) là dữ liệu sản phẩm:
  ```bash
  crontab: 0 2 * * * rsync -a --delete runs/ backup-host:/backups/autoqa-runs/
  ```
- `bots/` + code: git push (đã có GitHub private). Khôi phục: git revert / copy ngược rsync.

## Xoay key / thêm người

1. Admin đăng nhập UI → tab **Admin** → chọn người → "Xoay key" (key mới hiện một
   lần, gửi cho người dùng) hoặc thêm người mới / xoá người.
2. Không cần restart hay sửa env; `users.yaml` lưu key đã băm.
3. Người dùng nhập key mới vào UI (key cũ tự vô hiệu).

## Sự cố thường gặp

| Triệu chứng | Xử lý |
|---|---|
| Run toàn BLOCKED (HTTP/timeout) | bot target chết hoặc VPS mất mạng tới `live-demo.agenticai.pro.vn`; `curl` thử init endpoint; không phải lỗi tool |
| Lỗi LLM `thiếu biến môi trường` | `.env` thiếu/sai key; `docker compose exec autoqa env \| grep KEY` |
| 401 toàn bộ | key sai sau khi xoay; người dùng nhập lại key trong UI |
| Chạy mãi không xong / queue kẹt | `docker compose logs autoqa --tail 50`; restart service nếu job treo (conversation bot có thể còn mở — vô hại) |
| Đĩa đầy | `runs/` phình theo số run; nén run cũ > 30 ngày (`find runs -name '2026*.jsonl' -mtime +30 -exec gzip {} \;`) — INDEX vẫn đọc được (bổ sung giải nén khi mở) |
| Muốn chạy lại đúng 1 conversation bị cache bot | đổi persona phone hoặc chạy call mới (conversation_id mới) |

## An toàn booking (đọc trước khi bật gì liên quan đặt vé)

- Bot futa DEV (`FUTA_ALLOW_BOOKING=true`) tạo vé THẬT khi khách đồng ý bản xác nhận;
  KHÔNG có API hủy. Kịch bản mặc định dừng trước đồng ý.
- Nếu chạy nhầm tạo vé: ghi conv ID + thời điểm vào trang "vé cần hủy" (M3) hoặc
  file `runs/VE-CAN-HUY.md`, nhắn TĐV xử lý. Không bao giờ xoá bằng tay trên ezbooking
  bằng tài khoản chung nếu không được giao.
