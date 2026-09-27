"""Người dùng auto-qa — store `users.yaml` (key đã băm) + bootstrap admin qua env.

Không DB: file YAML là nguồn chân. Key thô chỉ hiện MỘT lần khi admin tạo/xoay
(trả về từ lời gọi, không lưu). So sánh bằng SHA-256.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from pathlib import Path

import yaml

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,31}$")
ROLES = ("admin", "member")


class UsersError(Exception):
    """Yêu cầu người dùng không hợp lệ (trùng tên, sai vai trò…)."""


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class UserStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._users: list[dict] = self._load()

    # ---------- load/save ----------

    def _load(self) -> list[dict]:
        if not self.path.is_file():
            return []
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or []
        if not isinstance(data, list):
            raise UsersError(f"{self.path}: users.yaml phải là danh sách")
        out = []
        for u in data:
            if not isinstance(u, dict) or not all(k in u for k in ("name", "key_hash", "role")):
                raise UsersError(f"{self.path}: mục user thiếu name/key_hash/role")
            out.append({"name": str(u["name"]), "key_hash": str(u["key_hash"]), "role": str(u["role"])})
        return out

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(yaml.safe_dump(self._users, allow_unicode=True), encoding="utf-8")

    def reload(self) -> None:
        self._users = self._load()

    # ---------- vòng đời ----------

    def bootstrap(self) -> None:
        """Store rỗng + có AUTOQA_ADMIN_KEY → tạo admin đầu tiên (chạy một lần lúc khởi động)."""
        key = os.environ.get("AUTOQA_ADMIN_KEY", "")
        if not self._users and key:
            self._users = [{"name": "admin", "key_hash": _hash(key), "role": "admin"}]
            self._save()

    @property
    def empty(self) -> bool:
        return not self._users

    def verify(self, key: str) -> tuple[str, str] | None:
        """Key thô → (name, role); sai/không có → None."""
        if not key:
            return None
        h = _hash(key)
        for u in self._users:
            if u["key_hash"] == h:
                return u["name"], u["role"]
        return None

    def _find(self, name: str) -> dict | None:
        return next((u for u in self._users if u["name"] == name), None)

    def add(self, name: str, role: str = "member") -> str:
        """Thêm người; trả key THÔ đúng một lần (không lưu key thô)."""
        if not NAME_RE.match(name or ""):
            raise UsersError(f"tên {name!r} không hợp lệ (a-z0-9 và . _ -, 2-32 ký tự)")
        if role not in ROLES:
            raise UsersError(f"vai trò {role!r} không hợp lệ (chọn {ROLES})")
        if self._find(name):
            raise UsersError(f"đã có người tên {name!r}")
        key = secrets.token_urlsafe(18)
        self._users.append({"name": name, "key_hash": _hash(key), "role": role})
        self._save()
        return key

    def rotate(self, name: str) -> str:
        u = self._find(name)
        if not u:
            raise UsersError(f"không có người tên {name!r}")
        key = secrets.token_urlsafe(18)
        u["key_hash"] = _hash(key)
        self._save()
        return key

    def set_role(self, name: str, role: str) -> None:
        if role not in ROLES:
            raise UsersError(f"vai trò {role!r} không hợp lệ (chọn {ROLES})")
        u = self._find(name)
        if not u:
            raise UsersError(f"không có người tên {name!r}")
        u["role"] = role
        self._save()

    def delete(self, name: str) -> None:
        u = self._find(name)
        if not u:
            raise UsersError(f"không có người tên {name!r}")
        self._users.remove(u)
        self._save()

    def listing(self) -> list[dict]:
        """Danh sách không chứa hash."""
        return [{"name": u["name"], "role": u["role"]} for u in self._users]
