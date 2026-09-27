# Hướng dẫn sử dụng — auto-qa (cho thành viên team)

> 5 phút onboarding. Công cụ nội bộ: mọi thao tác của bạn được ghi danh tính
> (ai chạy, ai review) — đó là điều tốt, đừng dùng key của người khác.

## 0. Lấy quyền truy cập

1. Nhờ admin thêm tên bạn trong tab **Admin** → bạn nhận một API key cá nhân
   (key chỉ hiện một lần — lưu ngay).
2. Mở địa chỉ auto-qa (hỏi owner), dán key vào ô **API key** góc phải → **Lưu key**.
3. Tên bạn hiện ở góc màn hình = đăng nhập xong.

## 1. Chạy test (tab **Chạy test**)

1. Chọn **bot** (vd. FUTA) → tick các kịch bản cần chạy (badge `llm` = có LLM caller
   đóng vai khách, tốn vài chục giây/cuộc).
2. Đọc **cảnh báo vàng** nếu có (vd. bot có thể tạo vé thật trên DEV) — đừng bỏ qua.
3. **Target đè** để trỏ mọi kịch bản vào một target (vd. thử bot mới); để trống = theo kịch bản.
4. **Số calls** (M1): muốn chạy cùng kịch bản N lần (bắt lỗi "lúc được lúc không")
   → tăng số này; mỗi call là một conversation riêng.
5. Bấm **Chạy test** → theo dõi tiến độ `x/N` → xong thấy bảng PASS/FAIL/BLOCKED
   kèm **conversation ID** (đây là mã truy vết khi trao đổi với team bot).

Chạy xong dữ liệu vào đâu: `runs/INDEX.md` (chỉ mục mọi run) + báo cáo MD/JSONL.
Server bận chạy giúp người khác trước? Bạn thấy **vị trí trong hàng đợi** — chờ chút.

## 2. Review transcript (tab **Lịch sử**) — việc quan trọng nhất

1. Lọc `chưa review` (M1) → mở một run → bung transcript kịch bản.
2. Đọc từng lượt **đối chiếu rubric** trong tab **Bot** → `knowledge/business.md`
   (mọi quy tắc CHUẨN/CẤM nằm đó, có nhãn nguồn).
3. Chấm **verdict**:
   - `ok` — bot đúng nghiệp vụ theo rubric.
   - `issue` — bot sai. **Bấm "neo lượt này" vào đúng lượt bị sai** (T7) rồi ghi ngắn
     gọn: bot nói gì / đúng ra phải nói gì theo rule nào. Ví dụ note tốt:
     `"T5 lặp câu hỏi giờ dù khách đã nói — vi phạm quy tắc mốc ước lượng"`.
   - `warn` — đáng ngờ, chưa chắc vi phạm (rubric chưa rõ / dữ liệu DEV lỗi).
4. Lưu ý riêng cho bot futa: chuyến **404 chi tiết** (18:00, 21:00, 22:00…) là lỗi
   hệ thống DEV — đừng chấm bot sai vì chuyện đó (xem cảnh báo cuối business.md).

Quy ước: 1 người – 1 verdict cho mỗi (kịch bản, call); sửa ý kiến = chấm lại.

## 3. Đọc xu hướng (M2: tab **Dashboard**)

- Pass-rate theo kịch bản theo tuần; kịch bản đỏ nhiều = ưu tiên sửa prompt.
- Tỉ lệ đã review của tuần — mục tiêu: không để transcript chưa ai đọc.

- Sửa goal, max_turns, mix, forbidden_phrases… form tự validate; lưu sai cú pháp sẽ bị chặn.
- Mỗi lần lưu = 1 commit git mang tên bạn — sửa hỏng thì bảo owner `git revert`.

## 5. Khi phát hiện bot sai nghiệp vụ

1. Review verdict `issue` + neo lượt + note căn cứ rubric (chưa có rubric cho случая
   đó? ghi `warn` + đề xuất bổ sung rubric vào `knowledge/business.md`).
2. Prompt engineer đọc tab issue aggregate → sửa bot/kịch bản → chạy lại kịch bản đó.
3. Issue hết: người phát hiện chấm lại `ok` ở run mới.

## 6. Đừng làm

- Đừng nói "đồng ý đặt" khi thử tay nếu chưa chắc nó an toàn (tạo vé thật trên DEV).
- Đừng xóa file trong `runs/` — lịch sử là của chung.
- Đừng gửi transcript ra ngoài team (có dữ liệu khách của bot).
