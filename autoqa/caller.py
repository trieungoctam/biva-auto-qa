"""Caller LLM — đóng vai khách hàng, sinh lời thoại từng lượt theo mục tiêu.

Không có kịch bản cố định: mỗi lượt, model nhìn (persona, goal, context tài liệu,
call script mẫu văn phong, lịch sử, số lượt còn lại) rồi trả JSON {"say","done","note"}.
`done=true` là tín hiệu kết thúc có chủ đích — driver dừng, không gửi thêm.

Call script thật (nếu kịch bản cung cấp) chỉ dùng làm MẪU VĂN PHONG: bắt chước
cách xưng hô, từ đệm, độ dài câu — tuyệt đối không chép nội dung mẫu.
"""

from __future__ import annotations

from autoqa.llm import ChatJsonModel, LlmError
from autoqa.scenario import Scenario

SYSTEM = """Bạn là KHÁCH HÀNG gọi vào tổng đài bán vé xe khách.
Nhiệm vụ: hội thoại theo đúng persona và mục tiêu đã cho, mỗi lượt nói MỘT câu tự nhiên như đang gọi điện thật.

Quy tắc:
- Chỉ viết lời của KHÁCH; tuyệt đối không bịa lời của tổng đài.
- Tiếng Việt NÓI tự nhiên, ngắn (dưới ~20 từ mỗi lượt), đúng văn phong của mẫu call script nếu có.
- Nếu có "Mẫu văn phong": bắt chước cách xưng hô, từ đệm, tốc độ câu của mẫu — KHÔNG chép nội dung mẫu; nội dung luôn bám mục tiêu.
- Bám mục tiêu: hỏi đủ thông tin mình cần, xác nhận khi đủ, không lan man.
- Khi mục tiêu đã đạt (đủ thông tin/đã xác nhận xong), đặt done=true, say để rỗng.
- Nếu tổng đài đã kết thúc hoặc lặp không tiến triển, đặt done=true và ghi rõ trong note.

Luôn trả đúng JSON: {"say": "<lời khách>", "done": true|false, "note": "<lý do done / còn thiếu gì>"}"""

_SCRIPT_MAX_CHARS = 4000  # mỗi transcript mẫu cắt ngắn để giữ prompt caller trong ngân sách


def _render_history(transcript: list[dict]) -> str:
    if not transcript:
        return "(chưa có — bạn sẽ nói câu đầu tiên)"
    lines = []
    for row in transcript:
        lines.append(f"Khách: {row['user']}")
        lines.append(f"Tổng đài: {row['assistant'] or '(im lặng)'}")
    return "\n".join(lines)


def _scripts_section(scenario: Scenario) -> str:
    if not scenario.call_scripts:
        return "(không có mẫu — nói tự nhiên, ngắn gọn như gọi điện thật)"
    return "\n---\n".join(s[:_SCRIPT_MAX_CHARS] for s in scenario.call_scripts)


async def next_turn(llm: ChatJsonModel, scenario: Scenario, transcript: list[dict]) -> dict:
    if scenario.max_turns is None:
        raise LlmError(f"{scenario.id}: kịch bản mode llm thiếu max_turns")
    remaining = scenario.max_turns - len(transcript)
    user = (
        f"Persona: {scenario.persona}\n"
        f"Mục tiêu của khách: {scenario.goal}\n"
        f"Tài liệu/bối cảnh: {(scenario.effective_context) or '(không có)'}\n\n"
        f"Mẫu văn phong (call script thật):\n{_scripts_section(scenario)}\n\n"
        f"Lịch sử hội thoại:\n{_render_history(transcript)}\n\n"
        f"Còn {remaining} lượt. Hãy trả lượt kế tiếp của KHÁCH (JSON như đã hướng dẫn)."
    )
    data = await llm.chat_json(system=SYSTEM, user=user)
    if not isinstance(data, dict) or "say" not in data:
        raise LlmError(f"caller trả thiếu trường 'say': {data!r}")
    say = data["say"]
    if not isinstance(say, str):
        raise LlmError(f"caller trả 'say' không phải chuỗi: {say!r}")
    return {
        "say": say,
        "done": bool(data.get("done", False)),
        "note": str(data.get("note", "")),
    }
