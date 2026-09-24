"""LLM client tối tiểu, tương thích OpenAI (/chat/completions) — không SDK.

Provider preset trong config.yaml (mục llm / llm_caller):
    provider: openai | gemini | custom (custom khai base_url + api_key_env)
Gemini chạy qua endpoint tương thích OpenAI — chỉ khác base_url + biến key.

Model reasoning (gpt-5.4-mini…): khai reasoning_effort; khi có effort thì tự bỏ
temperature khỏi request (dòng này từ chối temperature tuỳ chỉnh).

Mọi lời gọi là JSON-mode (response_format json_object); server không hỗ trợ thì
bóc JSON từ nội dung. Lỗi mạng/HTTP/parse thử lại theo max_attempts.
"""

from __future__ import annotations
import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx


@runtime_checkable
class ChatJsonModel(Protocol):
    """Mọi thứ có chat_json(system, user) -> dict đều dùng làm LLM được (test fake gồm cả)."""

    async def chat_json(self, system: str, user: str) -> dict: ...



class LlmError(Exception):
    """Lỗi hạ tầng LLM — runner maps sang BLOCKED, không phán xét bot."""


PROVIDERS: dict[str, dict] = {
    "openai": {"base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"},
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_env": "GEMINI_API_KEY",
    },
}


def load_dotenv(path: str = ".env") -> None:
    """Nạp .env (KEY=VALUE) vào os.environ — chỉ điền khóa THIẾU, không đè env thật."""
    file = Path(path)
    if not file.exists():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@dataclass(frozen=True)
class LlmConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4o-mini"
    temperature: float = 0.2
    timeout_s: float = 60.0
    max_attempts: int = 3
    reasoning_effort: str | None = None  # none|low|medium|high cho model reasoning


def load_llm_config(raw: dict | None) -> LlmConfig | None:
    """Biến mục yaml (llm / llm_caller) thành LlmConfig.

    provider: openai | gemini | custom (custom phải khai base_url + api_key_env).
    Mọi mục đều phải khai 'model' tường minh.
    """
    if not raw:
        return None
    provider = str(raw.get("provider", "custom"))
    preset = PROVIDERS.get(provider)
    if preset is None and "base_url" not in raw:
        raise LlmError(
            f"provider {provider!r} không biết (chọn {sorted(PROVIDERS)} hoặc khai base_url/api_key_env)"
        )
    model = raw.get("model")
    if not model:
        raise LlmError("mục llm cần khai 'model' tường minh")
    source = preset or {}
    return LlmConfig(
        base_url=str(raw.get("base_url", source.get("base_url", ""))),
        api_key_env=str(raw.get("api_key_env", source.get("api_key_env", "OPENAI_API_KEY"))),
        model=str(model),
        temperature=float(raw.get("temperature", 0.2)),
        timeout_s=float(raw.get("timeout_s", 60.0)),
        max_attempts=int(raw.get("max_attempts", 3)),
        reasoning_effort=raw.get("reasoning_effort"),
    )

def build_llm_caller(config_path, scenarios) -> "LlmClient | None":
    """Caller LLM cho suite nếu có kịch bản mode llm; None nếu không cần.

    Dùng chung cho CLI và web UI — tránh đẻ hai logic cấu hình LLM.
    Ném LlmError nếu suite cần LLM mà config thiếu mục 'llm'.
    """
    if not any(getattr(s, "mode", "") == "llm" for s in scenarios):
        return None
    from autoqa.config import load_raw

    raw = load_raw(config_path)
    cfg = load_llm_config(raw.get("llm_caller")) or load_llm_config(raw.get("llm"))
    if cfg is None:
        raise LlmError(f"config {config_path} thiếu mục 'llm' cho kịch bản mode llm")
    return LlmClient(cfg)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json_content(content: str) -> dict:
    """JSON thuần, hoặc JSON nằm trong code fence, hoặc lấy đoạn {...} đầu tiên."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    fenced = _FENCE_RE.search(content)
    if fenced:
        return json.loads(fenced.group(1))
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end > start:
        return json.loads(content[start : end + 1])
    raise LlmError(f"phản hồi LLM không phải JSON: {content[:200]!r}")


class LlmClient:
    def __init__(self, cfg: LlmConfig, *, transport=None) -> None:
        self._cfg = cfg
        self._client = httpx.AsyncClient(timeout=cfg.timeout_s, transport=transport)

    @property
    def model(self) -> str:
        return self._cfg.model

    def _base_body(self, system: str, messages: list[dict], json_mode: bool) -> dict:
        body: dict = {
            "model": self._cfg.model,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if self._cfg.reasoning_effort:
            body["reasoning_effort"] = self._cfg.reasoning_effort
        else:
            body["temperature"] = self._cfg.temperature
        return body

    async def _post_chat(self, body: dict) -> str:
        api_key = os.environ.get(self._cfg.api_key_env, "")
        if not api_key:
            raise LlmError(f"thiếu biến môi trường {self._cfg.api_key_env}")
        last_exc: Exception | None = None
        for attempt in range(1, self._cfg.max_attempts + 1):
            try:
                resp = await self._client.post(
                    f"{self._cfg.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=body,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise LlmError(f"nội dung phản hồi không phải chuỗi: {type(content)}")
                return content
            except (httpx.HTTPError, KeyError, IndexError, LlmError) as exc:
                last_exc = exc
                if attempt < self._cfg.max_attempts:
                    await asyncio.sleep(0.5 * attempt)
        raise LlmError(f"LLM lỗi sau {self._cfg.max_attempts} lần thử: {last_exc!r}") from last_exc

    async def chat_json(self, system: str, user: str) -> dict:
        """JSON-mode: trả dict (khoan dung với fence/json nhúng)."""
        content = await self._post_chat(
            self._base_body(system, [{"role": "user", "content": user}], json_mode=True)
        )
        return parse_json_content(content)

    async def chat_text(self, system: str, messages: list[dict]) -> str:
        """Chat thường (không ép JSON) — dùng cho trợ lý trao đổi nghiệp vụ."""
        return await self._post_chat(self._base_body(system, messages, json_mode=False))

    async def aclose(self) -> None:
        await self._client.aclose()
