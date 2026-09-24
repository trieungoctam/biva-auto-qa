"""Trạng thái: PASS / FAIL / BLOCKED.

- PASS/FAIL: kết luận từ check deterministic (protocol) — chấm hợp đồng thoại
  quan sát được, không dùng LLM.
- BLOCKED: lỗi hạ tầng (mạng/HTTP/LLM) — chưa kết luận được bot.

Chất lượng NGHIỆP VỤ của lời bot không chấm tự động: người review đọc
transcript trong báo cáo/JSONL và tự kết luận.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"

_WORST = {PASS: 0, BLOCKED: 1, FAIL: 2}


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def worst(statuses: list[str]) -> str:
    """FAIL nặng hơn BLOCKED; BLOCKED là chưa kết luận được, FAIL là sai."""
    return max(statuses, key=lambda s: _WORST.get(s, -1)) if statuses else PASS
