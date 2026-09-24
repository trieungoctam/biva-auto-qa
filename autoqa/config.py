"""Target whitelist — nguồn chân lý duy nhất về host driver được phép bắn tới."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

KINDS = ("mock", "sse_chat")


class ConfigError(Exception):
    """Lỗi khai báo target trong config.yaml."""


@dataclass(frozen=True)
class Target:
    name: str
    kind: str
    base_url: str | None = None
    init_path: str | None = None
    bot_id: int | str | None = None
    chat_path: str = "/chat/stream"
    callcenter_phone: str | None = None
    customer_phone: str = "0987654321"
    request_from: str = "auto-qa"
    auth_token_env: str | None = None
    timeout_s: float = 60.0

    def with_overrides(self, bot_id: int | str | None = None) -> "Target":
        if bot_id is None:
            return self
        return replace(self, bot_id=bot_id)


def load_raw(path: str | Path) -> dict:
    """Đọc toàn bộ config.yaml (targets + llm) — dùng cho phần cấu hình ngoài targets."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"không tìm thấy config: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: config phải là map")
    return data

def load_config(path: str | Path) -> dict[str, Target]:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"không tìm thấy config: {path}")
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or not isinstance(raw.get("targets"), list):
        raise ConfigError(f"{path}: cần khoá 'targets' là danh sách")

    targets: dict[str, Target] = {}
    for item in raw["targets"]:
        if not isinstance(item, dict) or "name" not in item or "kind" not in item:
            raise ConfigError(f"{path}: mỗi target cần đủ 'name' và 'kind'")
        name, kind = str(item["name"]), str(item["kind"])
        if kind not in KINDS:
            raise ConfigError(f"{path}: target {name!r}: kind {kind!r} không hỗ trợ (chọn {KINDS})")
        if name in targets:
            raise ConfigError(f"{path}: target {name!r} khai báo hai lần")
        target = Target(
            name=name,
            kind=kind,
            base_url=item.get("base_url"),
            init_path=item.get("init_path"),
            chat_path=item.get("chat_path", "/chat/stream"),
            bot_id=item.get("bot_id"),
            callcenter_phone=item.get("callcenter_phone"),
            customer_phone=str(item.get("customer_phone", "0987654321")),
            request_from=str(item.get("request_from", "auto-qa")),
            auth_token_env=item.get("auth_token_env"),
            timeout_s=float(item.get("timeout_s", 60.0)),
        )
        if kind == "sse_chat":
            if not target.base_url or not target.init_path:
                raise ConfigError(
                    f"{path}: target sse_chat {name!r} cần đủ 'base_url' và 'init_path' "
                    "(init là bước bắt buộc theo tài liệu live-demo)"
                )
        targets[name] = target
    return targets


def resolve_target(targets: dict[str, Target], name: str) -> Target:
    try:
        return targets[name]
    except KeyError:
        known = ", ".join(sorted(targets)) or "(trống)"
        raise ConfigError(f"target {name!r} không có trong config. Đã khai báo: {known}") from None
