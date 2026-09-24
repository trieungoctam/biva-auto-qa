import asyncio
import json

import httpx
import pytest

from autoqa.llm import PROVIDERS, LlmClient, LlmConfig, LlmError, load_llm_config, parse_json_content

CFG = LlmConfig(base_url="http://llm.test/v1", api_key_env="TEST_KEY", max_attempts=2)


def _ok_response(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": content}}]}
    )


def test_parse_json_content_plain_fenced_and_embedded():
    assert parse_json_content('{"say": "a lô"}') == {"say": "a lô"}
    assert parse_json_content('```json\n{"done": true}\n```') == {"done": True}
    assert parse_json_content('trước {"say": "x"} sau') == {"say": "x"}
    with pytest.raises(LlmError):
        parse_json_content("không có json ở đây")


def test_load_llm_config_provider_presets():
    gemini = load_llm_config({"provider": "gemini", "model": "gemini-2.5-flash"})
    assert gemini.base_url == PROVIDERS["gemini"]["base_url"]
    assert gemini.api_key_env == "GEMINI_API_KEY"

    custom = load_llm_config({"base_url": "http://proxy/v1", "api_key_env": "MY_KEY", "model": "m1"})
    assert custom.base_url == "http://proxy/v1" and custom.model == "m1"

    with pytest.raises(LlmError, match="provider"):
        load_llm_config({"provider": "carrier-pigeon", "model": "x"})
    with pytest.raises(LlmError, match="model"):
        load_llm_config({"provider": "openai"})

    effort = load_llm_config({"provider": "openai", "model": "gpt-5.4-mini", "reasoning_effort": "low"})
    assert effort is not None and effort.reasoning_effort == "low"


def _capture_llm(monkeypatch, cfg: LlmConfig, requests: list[httpx.Request]) -> LlmClient:
    monkeypatch.setenv(cfg.api_key_env, "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _ok_response('{"say": "cho em hỏi lịch xe", "done": false, "note": ""}')

    return LlmClient(cfg, transport=httpx.MockTransport(handler))


def test_chat_json_sends_auth_and_json_mode(monkeypatch):
    requests: list[httpx.Request] = []
    client = _capture_llm(monkeypatch, CFG, requests)
    data = asyncio.run(client.chat_json("system", "user"))
    asyncio.run(client.aclose())

    assert data["say"] == "cho em hỏi lịch xe"
    request = requests[0]
    assert str(request.url) == "http://llm.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(request.content)
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == CFG.temperature
    assert "reasoning_effort" not in body


def test_reasoning_model_body_sends_effort_and_drops_temperature(monkeypatch):
    requests: list[httpx.Request] = []
    cfg = LlmConfig(
        base_url="http://llm.test/v1",
        api_key_env="TEST_KEY",
        model="gpt-5.4-mini",
        reasoning_effort="none",
    )
    client = _capture_llm(monkeypatch, cfg, requests)
    asyncio.run(client.chat_json("s", "u"))
    asyncio.run(client.aclose())

    body = json.loads(requests[0].content)
    assert body["reasoning_effort"] == "none"
    assert "temperature" not in body  # dòng reasoning từ chối temperature tuỳ chỉnh


def test_missing_api_key_is_llm_error(monkeypatch):
    monkeypatch.delenv("TEST_KEY", raising=False)
    client = LlmClient(CFG, transport=httpx.MockTransport(lambda r: _ok_response("{}")))
    with pytest.raises(LlmError, match="TEST_KEY"):
        asyncio.run(client.chat_json("s", "u"))


def test_retry_then_success(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-test")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="boom")
        return _ok_response('{"ok": 1}')

    client = LlmClient(CFG, transport=httpx.MockTransport(handler))
    data = asyncio.run(client.chat_json("s", "u"))
    asyncio.run(client.aclose())
    assert data == {"ok": 1} and calls["n"] == 2


def test_exhausted_retries_raise_llm_error(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-test")
    client = LlmClient(CFG, transport=httpx.MockTransport(lambda r: httpx.Response(500, text="x")))
    with pytest.raises(LlmError, match="lỗi sau 2 lần"):
        asyncio.run(client.chat_json("s", "u"))
