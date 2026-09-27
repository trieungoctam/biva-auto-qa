"""Db client: FakeDb semantics + Db REST shapes (MockTransport) + webui DB mode."""

import httpx
import pytest
from fastapi.testclient import TestClient

from autoqa.db import Db, FakeDb
from autoqa.webui import create_app


def test_fakedb_upsert_select_delete_pk_semantics():
    db = FakeDb()
    db.upsert("aq_reviews", {"run_id": "r", "scenario": "s", "call": "1/1", "reviewer": "lan", "verdict": "ok"}, "run_id,scenario,call,reviewer")
    # cùng pk → THAY thế, không nhân bản
    db.upsert("aq_reviews", {"run_id": "r", "scenario": "s", "call": "1/1", "reviewer": "lan", "verdict": "issue"}, "run_id,scenario,call,reviewer")
    rows = db.select("aq_reviews")
    assert len(rows) == 1 and rows[0]["verdict"] == "issue"
    # reviewer khác → thêm dòng
    db.upsert("aq_reviews", {"run_id": "r", "scenario": "s", "call": "1/1", "reviewer": "tam", "verdict": "ok"}, "run_id,scenario,call,reviewer")
    assert len(db.select("aq_reviews")) == 2
    db.delete("aq_reviews", {"reviewer": "eq.lan"})
    assert [r["reviewer"] for r in db.select("aq_reviews")] == ["tam"]


def test_push_run_and_index_roundtrip():
    db = FakeDb()
    rows = [
        {"suite": "futa", "scenario": "smoke", "call": "1/2", "target": "futa", "status": "PASS",
         "conversation_id": "c1", "checks": [], "transcript": [{"turn": 0, "user": "hi", "assistant": "lo"}]},
        {"suite": "futa", "scenario": "smoke", "call": "2/2", "target": "futa", "status": "FAIL",
         "conversation_id": "c2", "checks": [], "transcript": []},
    ]
    db.push_run("20260927-000001", rows, bot="futa", user="lan")
    idx = db.call_rows_as_index()
    assert [(r["scenario"], r["status"], r["user"]) for r in idx] == [("futa/smoke", "PASS", "lan"), ("futa/smoke", "FAIL", "lan")]
    back = db.call_rows_as_jsonl("20260927-000001")
    assert back[0]["suite"] == "futa" and back[0]["scenario"] == "smoke"
    assert back[0]["transcript"][0]["assistant"] == "lo"
    db.save_review({"run_id": "20260927-000001", "scenario": "futa/smoke", "call": "1/2", "reviewer": "lan", "verdict": "ok"})
    assert db.reviews("20260927-000001")[0]["verdict"] == "ok"


def test_db_rest_shapes_with_mock_transport():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = str(request.url.path)
        seen["params"] = dict(request.url.params)
        seen["prefer"] = request.headers.get("Prefer", "")
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json=[])

    db = Db(url="http://supa.test", key="secret-key", transport=httpx.MockTransport(handler))
    assert db.enabled
    db.select("aq_users", {"name": "eq.lan"}, order="name.asc", limit=5)
    assert seen["path"] == "/rest/v1/aq_users"
    assert seen["params"]["name"] == "eq.lan" and seen["params"]["order"] == "name.asc" and seen["params"]["limit"] == "5"
    assert seen["auth"] == "Bearer secret-key"


def test_db_disabled_without_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "")
    assert not Db().enabled
    assert Db().maybe(lambda: "x") is None  # maybe tắt → None, caller fallback file


@pytest.fixture
def db_client(tmp_path, monkeypatch):
    """Web UI ở DB mode với FakeDb — chứng minh wiring (không mạng)."""
    monkeypatch.setenv("AUTOQA_ADMIN_KEY", "admin-key-x")
    bots = tmp_path / "bots" / "mockbot"
    (bots / "knowledge").mkdir(parents=True)
    (bots / "scenarios").mkdir()
    (bots / "knowledge" / "business.md").write_text("# Nghiệp vụ\nquy tắc", encoding="utf-8")
    (bots / "profile.yaml").write_text(
        "bot: mockbot\ndisplay_name: Bot\ntarget: mock\nbusiness_file: knowledge/business.md\n", encoding="utf-8"
    )
    (bots / "scenarios" / "smoke.yaml").write_text(
        "mode: script\nsuite: mockbot\nname: smoke\ntarget: mock\nturns:\n  - say: hi\n", encoding="utf-8"
    )
    (tmp_path / "config.yaml").write_text("targets:\n  - name: mock\n    kind: mock\n", encoding="utf-8")
    (tmp_path / "runs").mkdir()
    fake = FakeDb()
    app = create_app(
        bots_dir=tmp_path / "bots", runs_dir=tmp_path / "runs", config_path=tmp_path / "config.yaml",
        users_file=tmp_path / "users.yaml", schedules_file=tmp_path / "schedules.yaml", db=fake,
    )
    with TestClient(app) as c:
        app.state.admin_key = "admin-key-x"
        yield c, fake, tmp_path


def test_webui_db_mode_end_to_end(db_client):
    import time

    c, fake, tmp_path = db_client
    assert c.get("/api/me", headers={"X-API-Key": "admin-key-x"}).json()["name"] == "admin"

    r = c.post("/api/runs", json={"bot": "mockbot", "scenarios": ["mockbot/smoke"]}, headers={"X-API-Key": "admin-key-x"})
    run_id = r.json()["run_id"]
    s = {"status": "running"}
    for _ in range(100):
        s = c.get(f"/api/runs/{run_id}/status", headers={"X-API-Key": "admin-key-x"}).json()
        if s["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    assert s["status"] == "done"

    # run + calls nằm trong DB
    assert [x["run_id"] for x in fake.select("aq_runs")] == [run_id]
    calls = fake.select("aq_calls", {"run_id": f"eq.{run_id}"})
    assert len(calls) == 1 and calls[0]["scenario"] == "mockbot/smoke"

    # lịch sử + review đọc từ DB (xoá file local để chứng minh không đọc file)
    (tmp_path / "runs" / f"{run_id}.jsonl").unlink()
    (tmp_path / "runs" / "INDEX.md").unlink()
    rows = c.get("/api/runs", headers={"X-API-Key": "admin-key-x"}).json()
    assert rows and rows[0]["run"] == run_id and rows[0]["scenario"] == "mockbot/smoke"
    c.post(f"/api/runs/{run_id}/review", json={"scenario": "mockbot/smoke", "verdict": "ok"},
           headers={"X-API-Key": "admin-key-x"})
    assert fake.reviews(run_id)[0]["reviewer"] == "admin"
    detail = c.get(f"/api/runs/{run_id}", headers={"X-API-Key": "admin-key-x"}).json()
    assert detail["scenarios"][0]["transcript"][0]["user"] == "hi"

    # editor knowledge ghi cả DB lẫn file
    c.put("/api/bots/mockbot/knowledge", json={"business": "# Mới\nr1"},
          headers={"X-API-Key": "admin-key-x"})
    assert fake.select("aq_bots")[0]["business"] == "# Mới\nr1"
    assert (tmp_path / "bots" / "mockbot" / "knowledge" / "business.md").read_text(encoding="utf-8") == "# Mới\nr1"
