"""Mock bot offline — cùng hợp đồng ChatSession, lời thoại cố định theo lượt.

Mô phỏng ngữ nghĩa đếm lượt của callbot demo BIVA:
- lượt khách rỗng hoặc "<silence>" không phát nội dung và không tăng lượt;
- sau câu kết |ENDCALL, các lượt sau chỉ trả |ENDCALL không lời.
Dùng để tự kiểm tra harness (driver, oracle, runner, report) không cần mạng.
"""

from __future__ import annotations

from autoqa.adapter import AssistantReply, split_tag
from autoqa.config import Target

_SCRIPT: tuple[str, ...] = (
    "Dạ tối mai bên em có chuyến 23:30 và 23:59.|CHAT",
    "Giường nằm B1D giá 350.000đ ạ.|CHAT",
    "Em xác nhận: anh Tâm, một vé 23:59 mai, giường B1D.|CHAT",
    "Em đã ghi nhận đầy đủ thông tin. Cảm ơn anh.|ENDCALL",
)


class MockSession:
    def __init__(self, target: Target) -> None:
        if target.kind != "mock":
            raise ValueError(f"MockSession không chạy cho target {target.name!r}")
        self._turn = 0

    async def start(self) -> None:  # mock không cần init
        return None

    async def send(self, user_text: str) -> AssistantReply:
        text = user_text.strip()
        if not text or text == "<silence>":
            return AssistantReply("", None)
        reply = _SCRIPT[self._turn] if self._turn < len(_SCRIPT) else "|ENDCALL"
        self._turn += 1
        return AssistantReply(reply, split_tag(reply)[1])

    async def aclose(self) -> None:
        return None
