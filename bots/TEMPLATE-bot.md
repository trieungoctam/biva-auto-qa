# Kiến trúc dữ liệu theo bot — raw vs knowledge

Mỗi bot một thư mục khép kín trong `bots/<bot>/`. Ranh giới raw/processed là
hợp đồng của cả repo:

```
bots/<bot>/
  raw/                  # TÀI LIỆU GỐC — chỉ tồn tại ở máy local (gitignore)
  knowledge/            # SẢN PHẨM ĐÃ XỬ LÝ — nguồn trust duy nhất, push được
    business.md         #   nghiệp vụ nền bot (rubric)
    call-scripts/*.txt  #   mẫu văn phong (đã ẩn danh, tuyển chọn)
  situations/           # TÌNH HUỐNG tái sử dụng — mix được vào nhiều kịch bản
  profile.yaml          # hồ sơ bot: kết nối + TRỎ tới knowledge (không nhúng nội dung)
  scenarios/*.yaml      # kịch bản đã define sẵn (mode llm mix được nhiều tình huống)
```

## Ranh giới hai lớp dữ liệu

| | `raw/` | `knowledge/` |
|---|---|---|
| Bản chất | tài liệu gốc chưa qua tay: PDF, sheet, transcript gọi thật, chat log, FAQ thô | đầu ra của khâu xử lý: quy tắc nghiệp vụ, rubric, call script sạch |
| Đọc lúc chạy test | KHÔNG BAO GIỜ — code chỉ nhìn thấy knowledge/ | duy nhất nguồn mà profile/scenario tham chiếu |
| Push lên cloud | không bao giờ | đúng thứ được push (tri thức bot đã xử lý) |
| Git | `bots/*/raw/` nằm trong `.gitignore` | commit bình thường |

## Quy trình một bot

1. Kéo tài liệu gốc vào `bots/<bot>/raw/` — thoải mái bừa bộn, đây là vùng thô.
2. Agent xử lý Ở LOCAL: trích quy tắc → `knowledge/business.md`; chọn + ẩn danh
   transcript thật → `knowledge/call-scripts/*.txt`. Mọi biên tập diễn ra trước
   bước này; sau bước này knowledge là nguồn trust, không sửa tạm bừa.
3. Điền `profile.yaml` (kết nối + `business_file` + `call_scripts`) — checklist
   dưới đây. Thêm target vào `config.yaml` (whitelist, URL không bao giờ nằm ở kịch bản).
4. Viết kịch bản trong `scenarios/` — mỗi file chỉ khai phần RIÊNG (persona, goal,
   `context` luật riêng, `forbidden_phrases`); nghiệp vụ nền kế thừa qua profile.
   Đừng viết cứng một kịch bản một tình huống: tách tình huống lặp lại thành
   module rồi `mix:` — một cuộc gọi chạy đan nhiều tình huống:

   ```yaml
   # bots/<bot>/situations/tre-em-phu-thu.yaml — mảnh dùng lại
   name: tre-em-phu-thu
   goal: |
     Có thêm một trẻ em đi cùng; hỏi chiều cao bé theo quy tắc phụ thu.
   context: |
     - Bé 1m2 → phải được báo phụ thu 150.000đ.
   forbidden_phrases: ["miễn phí cho bé"]
   extra_turns: 3
   ```

   ```yaml
   # bots/<bot>/scenarios/dat-ve-kem-tre-em.yaml — kịch bản mix
   mode: llm
   name: dat-ve-kem-tre-em
   goal: "Đặt vé cho 2 người lớn đi Đà Lạt tối mai"
   mix: [tre-em-phu-thu, doi-y-chon-gio]   # nhiều tình huống trong MỘT cuộc gọi
   max_turns: 10                            # + extra_turns của mỗi tình huống
   ```

   Khi mix: goal nối thêm mục tiêu của từng tình huống, `context` nối luật,
   `forbidden_phrases` hợp lại (không trùng), `persona` gộp (tình huống thắng
   key trùng), `max_turns` cộng `extra_turns`. `mix` chỉ dùng cho mode llm.
5. Push `knowledge/` lên cloud bot (tri thức đã xử lý). Chạy lại test:

```
python -m autoqa run --suite 'bots/<bot>/scenarios/*.yaml' --target <tên-target>
```

6. Review chất lượng output bằng người: đọc transcript trong `runs/<id>.jsonl`
   + `runs/<id>.md`. Không có LLM judge — chữ trong transcript là căn cứ duy nhất.

## Checklist tiếp nhận bot mới

> (thiếu mục 4-5 vẫn chạy được; thiếu mục 1-2 thì chưa chạy được)

## 1. Kết nối & chứng thực (BẮT BUỘC)

- `target` trong `config.yaml`: name / base_url / init_path / chat_path / bot_id:
- Auth token đọc từ biến môi trường (khai `auth_token_env`):
- Bot chỉ được bắn vào host trong whitelist — không thêm host ngoài config.

## 2. Hồ sơ bot (BẮT BUỘC)

- `bots/<bot>/profile.yaml`: `bot:` (tên trùng tên thư mục), `display_name:`,
  `target:`, `business_file: knowledge/business.md`, `defaults: {max_turns, persona}`.
- Kịch bản khai `profile: <bot>` phải khớp `bot:` — driver chặn áp nhầm profile.

## 3. Nghiệp vụ nền → `knowledge/business.md` (BẮT BUỘC)

- Nguồn: tài liệu trong `raw/` (bảng giá, chính sách trẻ em/đoàn, FAQ, quy trình).
- Hình thức: mỗi quy tắc một dòng, nêu rõ hành vi CHUẨN và hành vi CẤM.
- Đây là rubric mọi kịch bản dùng chung — viết càng sắc, review càng nhanh.

## 4. Call script thật — mẫu văn phong caller (NÊN CÓ)

- 1–5 transcript cuộc gọi THẬT đã ẩn danh (tên/SĐT/định danh) vào
  `knowledge/call-scripts/*.txt`, định dạng mỗi dòng:
  ```
  Khách: ...
  Tổng đài: ...
  ```
- Điểm văn phong muốn giữ (từ đệm, xưng hô, câu ngắn/dài, vùng miền):
  (caller chỉ bắt chước văn phong — tuyệt đối không chép nội dung mẫu)

## 5. Ma trận kịch bản cần phủ (NÊN CÓ)

- Persona mẫu (tên, kiểu khách: ngoan / gắt / đổi ý / lẩm bẩm):
- Mục tiêu cuộc gọi cần test (goal): hỏi giá / đặt vé / đổi giờ / hỏi khuyến mãi / ngoài phạm vi / phàn nàn…
- Cụm KHÔNG BAO GIỜ được xuất hiện trong lời bot (`forbidden_phrases`):
- `max_turns` hợp lý cho loại cuộc gọi này (mặc định 8):

## 6. Tiêu chí chấm

- Rubric riêng ngoài mục 3 (nếu có):
- Ngưỡng nói "bot đạt" (vd: 100% smoke, ≥ 90% goal-driven):
  (lớp protocol chấm tự động; chất lượng nghiệp vụ người review đọc transcript tự kết luận)
