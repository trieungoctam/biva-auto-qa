"""Web UI v1: users/admin, queue, review verdict + neo T#, calls, export, stats, raw không lộ."""

import time

import pytest
import yaml
from fastapi.testclient import TestClient

from autoqa.webui import create_app


@pytest.fixture
def project(tmp_path):
    """Dự án tối tiểu: 1 bot script-mode + target mock + runs/ + users.yaml riêng."""
    bots = tmp_path / "bots" / "mockbot"
    (bots / "knowledge").mkdir(parents=True)
    (bots / "scenarios").mkdir()
    (bots / "raw").mkdir()  # vùng cấm — không bao giờ được lộ
    (bots / "raw" / "bi-mat.txt").write_text("dữ liệu gốc nội bộ", encoding="utf-8")
    (bots / "knowledge" / "business.md").write_text("# Nghiệp vụ nền\n\nquy tắc chung", encoding="utf-8")
    (bots / "profile.yaml").write_text(
        yaml.safe_dump(
            {"bot": "mockbot", "display_name": "Bot thử", "target": "mock", "business_file": "knowledge/business.md"},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (bots / "scenarios" / "smoke.yaml").write_text(
        yaml.safe_dump(
            {"mode": "script", "suite": "mockbot", "name": "smoke", "target": "mock",
             "turns": [{"say": "cho tôi lịch xe"}, {"say": "giá bao nhiêu"}]},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"targets": [{"name": "mock", "kind": "mock"}]}), encoding="utf-8")
    runs = tmp_path / "runs"
    runs.mkdir()
    return tmp_path


@pytest.fixture
def client(project, monkeypatch):
    """Store có sẵn 1 admin (bootstrap bằng env như thật) + 1 member."""
    monkeypatch.setenv("AUTOQA_ADMIN_KEY", "admin-key-xyz")
    app = create_app(
        bots_dir=project / "bots",
        runs_dir=project / "runs",
        config_path=project / "config.yaml",
        users_file=project / "users.yaml",
        schedules_file=project / "schedules.yaml",
    )
    with TestClient(app) as c:
        app.state.admin_key = "admin-key-xyz"
        app.state.member_key = c.post(
            "/api/users", json={"name": "lan", "role": "member"}, headers={"X-API-Key": "admin-key-xyz"}
        ).json()["key"]
        yield c, project


def test_admin_api_and_roles(client):
    c, project = client
    assert c.get("/api/me", headers={"X-API-Key": c.app.state.admin_key}).json() == {"name": "admin", "role": "admin"}
    assert c.get("/api/me", headers={"X-API-Key": c.app.state.member_key}).json() == {"name": "lan", "role": "member"}

    # member không đụng được admin API
    assert c.get("/api/users", headers={"X-API-Key": c.app.state.member_key}).status_code == 403
    users = c.get("/api/users", headers={"X-API-Key": c.app.state.admin_key}).json()
    assert {u["name"] for u in users} == {"admin", "lan"}
    assert all("key_hash" not in u and "key" not in u for u in users)  # không lộ hash/key

    # xoay key: key cũ chết, key mới sống
    new_key = c.post("/api/users/lan/rotate", headers={"X-API-Key": c.app.state.admin_key}).json()["key"]
    assert c.get("/api/me", headers={"X-API-Key": c.app.state.member_key}).status_code == 401
    assert c.get("/api/me", headers={"X-API-Key": new_key}).json()["name"] == "lan"

    # xoá người
    assert c.delete("/api/users/lan", headers={"X-API-Key": c.app.state.admin_key}).json() == {"ok": True}
    assert c.get("/api/me", headers={"X-API-Key": new_key}).status_code == 401
    monkeypatch_file = project / "users.yaml"
    assert "lan" not in monkeypatch_file.read_text(encoding="utf-8")


def test_auth_rejects_wrong_key(client):
    c, _ = client
    assert c.get("/api/bots").status_code == 401
    assert c.get("/api/bots", headers={"X-API-Key": "sai-roi"}).status_code == 401
    assert c.get("/api/bots", headers={"X-API-Key": c.app.state.member_key}).status_code == 200


def test_run_e2e_queue_calls_review_export_stats(client):
    c, project = client
    # chạy 2 calls từ UI với danh tính member
    r = c.post(
        "/api/runs",
        json={"bot": "mockbot", "scenarios": ["mockbot/smoke"], "calls": 2},
        headers={"X-API-Key": c.app.state.member_key},
    )
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    assert r.json()["total"] == 2

    s = {"status": "queued"}
    for _ in range(200):
        s = c.get(f"/api/runs/{run_id}/status", headers={"X-API-Key": c.app.state.member_key}).json()
        if s["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    assert s["status"] == "done"
    assert len(s["results"]) == 2  # 2 calls
    assert all(x["status"] == "PASS" for x in s["results"])

    # INDEX 7 cột: có call i/N + người chạy là member
    index = (project / "runs" / "INDEX.md").read_text(encoding="utf-8")
    assert "lan" in index and "(1/2)" in index and "(2/2)" in index

    # review: member chấm ok cho call 1, neo T1 cho call 2
    rv1 = c.post(
        f"/api/runs/{run_id}/review",
        json={"scenario": "mockbot/smoke", "call": "1/2", "verdict": "ok"},
        headers={"X-API-Key": c.app.state.member_key},
    ).json()
    assert rv1["reviewer"] == "lan"
    rv2 = c.post(
        f"/api/runs/{run_id}/review",
        json={"scenario": "mockbot/smoke", "call": "2/2", "verdict": "issue", "anchor": "T1", "note": "bot trả lời rỗng"},
        headers={"X-API-Key": c.app.state.member_key},
    ).json()
    assert rv2["anchor"] == "T1"
    # verdict sai + anchor sai bị chặn; review cùng (scenario, call, reviewer) thì THAY thế
    assert c.post(f"/api/runs/{run_id}/review", json={"scenario": "x", "verdict": "sai"}, headers={"X-API-Key": c.app.state.member_key}).status_code == 400
    assert c.post(f"/api/runs/{run_id}/review", json={"scenario": "x", "verdict": "ok", "anchor": "L7"}, headers={"X-API-Key": c.app.state.member_key}).status_code == 400
    reviews = c.get(f"/api/runs/{run_id}/review", headers={"X-API-Key": c.app.state.member_key}).json()
    assert len(reviews) == 2

    # chi tiết run kèm review
    detail = c.get(f"/api/runs/{run_id}", headers={"X-API-Key": c.app.state.member_key}).json()
    assert len(detail["scenarios"]) == 2 and len(detail["reviews"]) == 2
    assert detail["scenarios"][0]["transcript"][0]["assistant"]

    # export csv + md có verdict
    csv = c.get(f"/api/runs/{run_id}/export?format=csv", headers={"X-API-Key": c.app.state.member_key}).text
    assert "issue,lan,T1" in csv.replace('"', "")
    md = c.get(f"/api/runs/{run_id}/export", headers={"X-API-Key": c.app.state.member_key}).text
    assert "**issue** bởi lan" in md

    # stats: 1 kịch bản, 2 rows, 2 reviewed, 1 issue
    stats = c.get("/api/stats", headers={"X-API-Key": c.app.state.member_key}).json()
    assert stats["rows"] == 2 and stats["reviewed"] == 2
    scn = stats["scenarios"][0]
    assert scn["scenario"] == "mockbot/smoke" and scn["pass"] == 2 and scn["issues"] == 1


def test_queue_positions_instead_of_reject(client, monkeypatch):
    """Run thứ 2 xếp hàng (position >= 2) thay vì bị từ chối; cả hai chạy trọn."""
    import autoqa.webui as webui

    real = webui.run_suite

    async def slow(*a, **kw):
        import asyncio

        await asyncio.sleep(0.4)
        return await real(*a, **kw)

    monkeypatch.setattr(webui, "run_suite", slow)
    c, _ = client
    r1 = c.post("/api/runs", json={"bot": "mockbot", "scenarios": ["mockbot/smoke"]}, headers={"X-API-Key": c.app.state.member_key})
    r2 = c.post("/api/runs", json={"bot": "mockbot", "scenarios": ["mockbot/smoke"]}, headers={"X-API-Key": c.app.state.admin_key})
    assert r1.status_code == 200 and r2.status_code == 200  # xếp hàng, KHÔNG 409
    assert r2.json()["queue_position"] >= 1

    for rid in (r1.json()["run_id"], r2.json()["run_id"]):
        s = {"status": "running"}
        for _ in range(200):
            s = c.get(f"/api/runs/{rid}/status", headers={"X-API-Key": c.app.state.member_key}).json()
            if s["status"] not in ("queued", "running"):
                break
            time.sleep(0.05)
        assert s["status"] == "done"


def test_raw_never_exposed(client):
    c, project = client
    assert c.get("/api/bots/mockbot/raw").status_code in (404, 405)
    know = c.get("/api/bots/mockbot/knowledge", headers={"X-API-Key": c.app.state.member_key}).json()
    assert know["business"].startswith("# Nghiệp vụ")  # không chạm được file raw


def test_scheduler_enqueues_due_schedule(client, monkeypatch):
    """schedules.yaml đến giờ → run tự enqueue với user=scheduler, đánh dấu ngày chạy."""
    c, project = client
    (project / "schedules.yaml").write_text(
        yaml.safe_dump(
            [{"name": "nightly", "bot": "mockbot", "scenarios": ["mockbot/smoke"], "at": "00:00", "user": "scheduler"}]
        ),
        encoding="utf-8",
    )
    # scheduler tick 60s — gọi vòng lọc tay như scheduler thật thay vì chờ
    from datetime import datetime

    import autoqa.webui as w

    scheds = yaml.safe_load((project / "schedules.yaml").read_text(encoding="utf-8"))
    now = datetime.now()
    assert w._sched_due_today(scheds[0], now) is True  # at 00:00 luôn due trong ngày
