"""Ranh giới adapter: harness không biết bot ở đâu, chỉ biết ChatSession."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from autoqa.config import Target
from autoqa.scenario import Scenario

_TAG_RE = re.compile(r"\|(ENDCALL|ENDCHAT|CHAT)")
_TAG_NORMALIZE = {"ENDCHAT": "ENDCALL"}


def split_tag(text: str) -> tuple[str, str | None]:
    """Tách tag cuối cùng trong lời bot (quy ước |CHAT/|ENDCALL của callbot BIVA).

    Trả về (lời nói đã bỏ tag, tag chuẩn hoá | None).
    """
    matches = list(_TAG_RE.finditer(text))
    if not matches:
        return text.strip(), None
    last = matches[-1]
    spoken = (text[: last.start()] + text[last.end() :]).strip()
    return spoken, _TAG_NORMALIZE.get(last.group(1), last.group(1))


@dataclass(frozen=True)
class AssistantReply:
    text: str  # toàn bộ chữ bot trả về (chưa strip tag)
    tag: str | None = None

    @property
    def spoken(self) -> str:
        return split_tag(self.text)[0]

    @property
    def normalized_tag(self) -> str | None:
        return split_tag(self.text)[1]


@runtime_checkable
class ChatSession(Protocol):
    async def start(self) -> None: ...

    async def send(self, user_text: str) -> AssistantReply: ...

    async def aclose(self) -> None: ...


def open_session(target: Target, scenario: Scenario, *, transport=None) -> ChatSession:
    """Mở phiên chat cho target đã khai báo. `transport` chỉ dùng cho test offline."""
    if target.kind == "mock":
        from autoqa.adapter.mock import MockSession

        return MockSession(target)
    from autoqa.adapter.sse_chat import SseChatSession

    return SseChatSession(target, scenario, transport=transport)
