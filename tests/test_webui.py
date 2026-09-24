"""Web UI: auth, listing bots, chạy run thật (mock target), INDEX, raw không lộ."""

import time

import pytest
import yaml
from fastapi.testclient import TestClient

from autoqa.webui import create_app


@pytest.fixture
def project(tmp_path):
    """Dự án tối tiểu: 1 bot script-mode + target mock + runs/ rỗng."""
    bots = tmp_path / "bots" / "mockbot"
    (bots / "knowledge").mkdir(parents=True)
    (bots / "scenarios").mkdir()
    (bots / "raw").mkdir()  # vùng cấm — không bao giờ được lộ
    (bots / "raw" / "bi-mat.txt").write_text("dữ liệu gốc nội bộ", encoding="utf-8")
    (bots / "knowledge" / "business.md").write_text(
        "# Nghiệp vụ nền\n\n## CẢNH BÁO KHI CHẠY TEST\n- không có gì nguy hiểm", encoding="utf-8"
    )
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
def client(project):
    app = create_app(bots_dir=project / "bots", runs_dir=project / "runs", config_path=project / "config.yaml")
    with TestClient(app) as c:
        yield c, project


def test_bots_listing_and_knowledge(client):
    c, project = client
    bots = c.get("/api/bots").json()
    assert [b["bot"] for b in bots] == ["mockbot"]
    assert bots[0]["n_scenarios"] == 1

    know = c.get("/api/bots/mockbot/knowledge").json()
    assert "CẢNH BÁO" in know["business"] and know["has_run_warning"] is True

    # kịch bản liệt kê đúng mode/số lượt
    scns = c.get("/api/bots/mockbot/scenarios").json()
    assert scns[0]["id"] == "mockbot/smoke" and scns[0]["turns"] == 2


def test_raw_never_exposed(client):
    c, project = client
    # không có endpoint nào chạm vào raw/ — mọi đường đều 404/400
    assert c.get("/api/bots/mockbot/raw").status_code in (404, 405)
    assert c.get("/api/bots/mockbot/knowledge?file=../raw/bi-mat.txt").json()["business"].startswith("# Nghiệp vụ")

def test_second_run_rejected_while_first_running(client, monkeypatch):
    c, _ = client
    """Hợp đồng lock: đang có run → request mới nhận 409."""
    import autoqa.webui as webui

    real_run_suite = webui.run_suite

    async def slow_run_suite(*args, **kwargs):  # job đủ dài để POST thứ 2 lao vào lock
        import asyncio

        await asyncio.sleep(0.4)
        return await real_run_suite(*args, **kwargs)

    monkeypatch.setattr(webui, "run_suite", slow_run_suite)
    r1 = c.post("/api/runs", json={"bot": "mockbot", "scenarios": ["mockbot/smoke"]})
    assert r1.status_code == 200
    r2 = c.post("/api/runs", json={"bot": "mockbot", "scenarios": ["mockbot/smoke"]})
    assert r2.status_code == 409

    run_id = r1.json()["run_id"]
    s = {"status": "running"}
    for _ in range(100):
        s = c.get(f"/api/runs/{run_id}/status").json()
        if s["status"] != "running":
            break
        time.sleep(0.05)
    assert s["status"] == "done"  # run 1 vẫn chạy trọn vẹn sau khi từ chối run 2


def test_auth_required_when_key_set(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv("AUTOQA_UI_KEY", "secret123")
    assert c.get("/api/bots").status_code == 401
    assert c.get("/api/bots", headers={"X-API-Key": "sai"}).status_code == 401
    assert c.get("/api/bots", headers={"X-API-Key": "secret123"}).status_code == 200
    monkeypatch.delenv("AUTOQA_UI_KEY")
