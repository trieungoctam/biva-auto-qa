import asyncio
import json
from pathlib import Path

import httpx

from autoqa.adapter.sse_chat import SseChatSession
from autoqa.config import Target
from autoqa.scenario import Scenario, Turn

TARGET = Target(
    name="live-test",
    kind="sse_chat",
    base_url="http://localhost:14496",
    init_path="/api/conversation/init",
    chat_path="/chat/stream",
    bot_id=1,
)

_SSE_BODY = (
    'data: {"content": "Dạ"}\n'
    'data: {"content": " bên em có chuyến 23:30.|CHAT"}\n'
    'data: {"turn": 0}\n'  # metadata JSON, không có trường chữ — bỏ qua
    'data: {"content": " nhé anh."}\n\n'
)


def _scenario() -> Scenario:
    return Scenario(
        path=Path("x"),
        suite="s",
        name="n",
        target="live-test",
        persona={"phone": "0912345678"},
        turns=(Turn(say="alô"),),
    )


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_init_then_chat_stream_and_urls_come_from_target_only():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/conversation/init":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_SSE_BODY.encode("utf-8"),
        )

    async def flow():
        session = SseChatSession(TARGET, _scenario(), transport=_transport(handler))
        await session.start()
        reply = await session.send("Tối mai có xe đi Đà Lạt không?")
        await session.aclose()
        return session, reply

    session, reply = asyncio.run(flow())

    # whitelist guard: mọi request đúng URL ghép từ target
    assert [str(r.url) for r in requests] == [
        "http://localhost:14496/api/conversation/init",
        "http://localhost:14496/chat/stream",
    ]

    init_body = json.loads(requests[0].content)
    assert init_body["conversation_id"] == session.conversation_id
    assert init_body["bot_id"] == 1
    assert init_body["customer_phone"] == "0912345678"  # persona đè phone mặc định

    chat_body = json.loads(requests[1].content)
    assert chat_body["message"] == "Tối mai có xe đi Đà Lạt không?"
    assert chat_body["conversation_id"] == session.conversation_id
    assert chat_body["request_from"] == "auto-qa"

    # nối chunk JSON + chuỗi thô, bỏ metadata; tag cuối được tách
    assert reply.spoken == "Dạ bên em có chuyến 23:30. nhé anh."
    assert reply.normalized_tag == "CHAT"


def test_plain_text_stream_without_sse_prefix_is_read_verbatim():
    """live-demo trả plain-text chunked (không 'data:') — phải đọc nguyên văn."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/conversation/init":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(
            200,
            headers={"content-type": "text/plain; charset=utf-8"},
            content="Xin lỗi, đang chuyển sang tập lệnh dự phòng.\nAnh chị cho em biết khung giờ ạ.".encode(
                "utf-8"
            ),
        )

    async def flow():
        session = SseChatSession(TARGET, _scenario(), transport=_transport(handler))
        await session.start()
        reply = await session.send("Tối mai có xe đi Đà Lạt không?")
        await session.aclose()
        return reply

    reply = asyncio.run(flow())
    assert "tập lệnh dự phòng" in reply.text
    assert "khung giờ" in reply.text
    assert reply.normalized_tag is None  # không có tag trong plain-text
