"""Adapter SSE cho callbot live-demo (hợp đồng API do team cung cấp).

Luồng một phiên:
1. POST {base_url}{init_path}  — bắt buộc trước, đăng ký conversation_id ở cache.
2. POST {base_url}{chat_path}  mỗi lượt — body message + conversation_id;
   server tự giữ lịch sử theo phiên đã init (DB đồng bộ async).
3. Đọc SSE: dòng "data: ..." — payload JSON lấy trường content/text/message,
   payload chuỗi thô tính là chữ; metadata (JSON không có trường chữ) bỏ qua.

URL chỉ được ghép từ target trong config (whitelist) — không bao giờ nhận URL
từ kịch bản. Không có đường code nào gọi webhook booking/giữ chỗ.
"""

from __future__ import annotations

import json
from uuid import uuid4

import httpx

from autoqa.adapter import AssistantReply, ChatSession, split_tag
from autoqa.config import Target
from autoqa.scenario import Scenario

_CONTENT_KEYS = ("content", "text", "message")


class SseChatSession(ChatSession):
    def __init__(self, target: Target, scenario: Scenario, *, transport=None) -> None:
        if not target.base_url or not target.init_path:
            raise ValueError(f"target {target.name!r} thiếu base_url/init_path")
        self._target = target
        base = target.base_url.rstrip("/")
        # path có thể chứa {bot_id} (hợp đồng platform aa3: /conversations/chat/stream/{bot_id}/init)
        fmt: dict[str, str] = {"bot_id": str(target.bot_id)} if target.bot_id is not None else {}
        init_path = target.init_path.format(**fmt) if "{" in target.init_path else target.init_path
        chat_path = target.chat_path.format(**fmt) if "{" in target.chat_path else target.chat_path
        self._init_url = f"{base}{init_path}"
        self._chat_url = f"{base}{chat_path}"
        self._conversation_id = f"autoqa-{uuid4().hex[:12]}"
        self._customer_phone = str(scenario.persona.get("phone") or target.customer_phone)
        self._index = 0
        self._client = httpx.AsyncClient(timeout=target.timeout_s, transport=transport)

    @property
    def conversation_id(self) -> str:
        return self._conversation_id

    async def start(self) -> None:
        body: dict = {
            "conversation_id": self._conversation_id,
            "customer_phone": self._customer_phone,
        }
        if self._target.bot_id is not None:
            body["bot_id"] = self._target.bot_id
        if self._target.callcenter_phone:
            body["callcenter_phone"] = self._target.callcenter_phone
        resp = await self._client.post(self._init_url, json=body)
        resp.raise_for_status()

    async def send(self, user_text: str) -> AssistantReply:
        body: dict = {
            "conversation_id": self._conversation_id,
            "message": user_text,
            "customer_phone": self._customer_phone,
            "request_from": self._target.request_from,
            "index": self._index,
        }
        if self._target.bot_id is not None:
            body["bot_id"] = self._target.bot_id
        if self._target.callcenter_phone:
            body["callcenter_phone"] = self._target.callcenter_phone
        self._index += 1

        chunks: list[str] = []
        raw_lines: list[str] = []  # live-demo trả plain-text chunked (không có prefix data:)
        saw_data = False
        async with self._client.stream("POST", self._chat_url, json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                raw_lines.append(line)
                if not line.startswith("data:"):
                    continue
                saw_data = True
                payload = line.removeprefix("data:")
                if payload.startswith(" "):  # SSE: bỏ đúng MỘT khoảng trắng sau dấu hai chấm
                    payload = payload[1:]
                if not payload:
                    continue
                chunks.append(_extract_content(payload))
        full = "".join(chunks) if saw_data else "\n".join(raw_lines).strip()
        return AssistantReply(full, split_tag(full)[1])

    async def aclose(self) -> None:
        await self._client.aclose()


def _extract_content(payload: str) -> str:
    """Một dòng data: → chữ. JSON lấy trường content/text/message, chuỗi thô giữ nguyên."""
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return payload
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        for key in _CONTENT_KEYS:
            value = obj.get(key)
            if isinstance(value, str):
                return value
    return ""  # JSON metadata (không có trường chữ) — bỏ qua
