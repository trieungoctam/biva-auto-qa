"""Supabase (PostgREST) — backend dữ liệu auto-qa khi env cấu hình.

Bảng `aq_*` (xem supabase/migrations/). Mọi truy vấn qua REST với service key:
SUPABASE_URL + SUPABASE_SERVICE_KEY. Không cấu hình → Db().enabled = False,
webui rơi về chế độ file (local dev / test không cần mạng).
"""

from __future__ import annotations

import os

import httpx


class DbError(Exception):
    """Lỗi truy vấn Supabase."""


class Db:
    def __init__(self, url: str | None = None, key: str | None = None, *, transport=None) -> None:
        self.url = (url if url is not None else os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = key if key is not None else os.environ.get("SUPABASE_SERVICE_KEY", "")
        self.enabled = bool(self.url and self.key)
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=f"{self.url}/rest/v1",
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
            },
            timeout=20.0,
            transport=self._transport,
        )

    # ---------- primitives ----------

    def select(self, table: str, filters: dict[str, str] | None = None, *, order: str = "", limit: int = 0) -> list[dict]:
        params: dict[str, str] = {"select": "*"}
        params.update(filters or {})
        if order:
            params["order"] = order
        if limit:
            params["limit"] = str(limit)
        with self._client() as c:
            r = c.get(f"/{table}", params=params)
        if r.status_code != 200:
            raise DbError(f"select {table}: {r.status_code} {r.text[:200]}")
        return r.json()

    def upsert(self, table: str, rows: list[dict] | dict, on_conflict: str) -> list[dict]:
        if isinstance(rows, dict):
            rows = [rows]
        if not rows:
            return []
        with self._client() as c:
            r = c.post(
                f"/{table}",
                params={"on_conflict": on_conflict},
                headers={"Prefer": "resolution=merge-duplicates,return=representation"},
                json=rows,
            )
        if r.status_code not in (200, 201):
            raise DbError(f"upsert {table}: {r.status_code} {r.text[:200]}")
        return r.json()

    def update(self, table: str, filters: dict[str, str], patch: dict) -> None:
        with self._client() as c:
            r = c.patch(f"/{table}", params=filters, json=patch)
        if r.status_code != 204:
            raise DbError(f"update {table}: {r.status_code} {r.text[:200]}")

    def delete(self, table: str, filters: dict[str, str]) -> None:
        with self._client() as c:
            r = c.delete(f"/{table}", params=filters)
        if r.status_code not in (204, 200):
            raise DbError(f"delete {table}: {r.status_code} {r.text[:200]}")

    def maybe(self, fn, *args, **kwargs):
        """Chạy truy vấn; Db tắt hoặc lỗi → None (caller tự fallback file)."""
        if not self.enabled:
            return None
        try:
            return fn(*args, **kwargs)
        except DbError:
            return None

    # ---------- helper dùng chung ----------

    def push_run(self, run_id: str, rows: list[dict], *, bot: str = "", user: str = "", status: str = "done", error: str | None = None) -> None:
        """Đẩy một run (từ dòng JSONL) lên aq_runs + aq_calls."""
        run = {
            "run_id": run_id,
            "bot": bot,
            "run_user": user,
            "status": status,
            "total": len(rows),
            "error": error,
        }
        calls = []
        for i, r in enumerate(rows):
            calls.append(
                {
                    "run_id": run_id,
                    "scenario": f"{r.get('suite')}/{r.get('scenario')}",
                    "call": str(r.get("call") or "1/1"),
                    "seq": i,
                    "target": str(r.get("target") or ""),
                    "run_user": user,
                    "status": str(r.get("status") or ""),
                    "conversation_id": str(r.get("conversation_id") or ""),
                    "error": r.get("error"),
                    "checks": r.get("checks") or [],
                    "transcript": r.get("transcript") or [],
                }
            )
        self.upsert("aq_runs", run, "run_id")
        if calls:
            self.upsert("aq_calls", calls, "run_id,scenario,call")

    def call_rows_as_index(self, limit: int = 3000) -> list[dict]:
        """aq_calls → dạng dòng INDEX cho webui (mới nhất trước)."""
        rows = self.select("aq_calls", order="run_id.desc,seq.asc", limit=limit)
        out = []
        for r in rows:
            out.append(
                {
                    "run": r["run_id"],
                    "target": r.get("target") or "",
                    "scenario": r.get("scenario") or "",
                    "status": r.get("status") or "",
                    "conversation": r.get("conversation_id") or "",
                    "user": r.get("run_user") or "",
                    "report": "",
                }
            )
        return out

    def call_rows_as_jsonl(self, run_id: str) -> list[dict]:
        """aq_calls của một run → dạng dòng JSONL cho webui."""
        rows = self.select("aq_calls", {"run_id": f"eq.{run_id}"}, order="seq.asc")
        out = []
        for r in rows:
            scenario = str(r.get("scenario") or "/")
            out.append(
                {
                    "run_id": run_id,
                    "suite": scenario.split("/")[0],
                    "scenario": "/".join(scenario.split("/")[1:]) or scenario,
                    "call": r.get("call") or "1/1",
                    "conversation_id": r.get("conversation_id") or "",
                    "target": r.get("target") or "",
                    "checks": r.get("checks") or [],
                    "status": r.get("status") or "",
                    "error": r.get("error"),
                    "transcript": r.get("transcript") or [],
                }
            )
        return out

    def reviews(self, run_id: str) -> list[dict]:
        rows = self.select("aq_reviews", {"run_id": f"eq.{run_id}"}, order="ts.asc")
        return [
            {
                "scenario": r.get("scenario") or "",
                "call": r.get("call") or "1/1",
                "reviewer": r.get("reviewer") or "",
                "verdict": r.get("verdict") or "",
                "anchor": r.get("anchor") or "",
                "note": r.get("note") or "",
                "ts": str(r.get("ts") or ""),
            }
            for r in rows
        ]

    def save_review(self, entry: dict) -> None:
        run_id, scn, call, reviewer = entry["run_id"], entry["scenario"], entry["call"], entry["reviewer"]
        self.delete("aq_reviews", {"run_id": f"eq.{run_id}", "scenario": f"eq.{scn}", "call": f"eq.{call}", "reviewer": f"eq.{reviewer}"})
        self.upsert("aq_reviews", {k: v for k, v in entry.items() if k != "run_id"} | {"run_id": run_id}, "run_id,scenario,call,reviewer")


class FakeDb(Db):
    """Db in-memory cho test — cùng interface, không mạng."""

    def __init__(self):  # noqa: D102
        super().__init__(url="http://fake", key="fake")
        self.tables: dict[str, list[dict]] = {}
        self._pks = {
            "aq_users": ["name"],
            "aq_schedules": ["name"],
            "aq_bots": ["bot"],
            "aq_scenarios": ["bot", "name"],
            "aq_situations": ["bot", "name"],
            "aq_runs": ["run_id"],
            "aq_calls": ["run_id", "scenario", "call"],
            "aq_reviews": ["run_id", "scenario", "call", "reviewer"],
        }

    def _rows(self, table: str) -> list[dict]:
        return self.tables.setdefault(table, [])

    @staticmethod
    def _match(row: dict, filters: dict[str, str]) -> bool:
        for k, v in filters.items():
            op, _, val = v.partition(".")
            if op == "eq" and str(row.get(k)) != val:
                return False
        return True

    def select(self, table: str, filters: dict[str, str] | None = None, *, order: str = "", limit: int = 0) -> list[dict]:
        rows = [r for r in self._rows(table) if self._match(r, filters or {})]
        if order:
            col, _, direction = order.partition(".")
            rows = sorted(rows, key=lambda r: str(r.get(col, "")), reverse=direction == "desc")
        return rows[:limit] if limit else rows

    def upsert(self, table: str, rows: list[dict] | dict, on_conflict: str) -> list[dict]:
        pk = self._pks[table]
        if isinstance(rows, dict):
            rows = [rows]
        existing = self._rows(table)
        for row in rows:
            hit = next((e for e in existing if all(e.get(k) == row.get(k) for k in pk)), None)
            if hit:
                hit.update(row)
            else:
                existing.append(dict(row))
        return rows

    def update(self, table: str, filters: dict[str, str], patch: dict) -> None:
        for row in self._rows(table):
            if self._match(row, filters):
                row.update(patch)

    def delete(self, table: str, filters: dict[str, str]) -> None:
        self.tables[table] = [r for r in self._rows(table) if not self._match(r, filters)]
