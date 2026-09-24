from pathlib import Path

import asyncio
import json

import httpx

from autoqa.config import Target
from autoqa.runner import run_scenario, run_suite
from autoqa.scenario import Scenario, Turn


def _scenario(yaml_name: str, turns: list[Turn], forbidden: tuple[str, ...] = ()) -> Scenario:
    from pathlib import Path

    return Scenario(
        path=Path(yaml_name),
        suite="s",
        name=yaml_name.removesuffix(".yaml"),
        target="mock",
        turns=tuple(turns),
        forbidden_phrases=forbidden,
    )


def _run(scenario: Scenario, transport=None):
    from autoqa.config import load_config
    from pathlib import Path

    targets = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    return asyncio.run(run_scenario(targets["mock"], scenario, transport=transport))


def test_mock_happy_path_passes():
    turns = [Turn(say=f"turn {i}") for i in range(4)]
    result = _run(_scenario("happy.yaml", turns))
    assert result.status == "PASS"
    assert len(result.transcript) == 4
    assert result.transcript[-1]["tag"] == "ENDCALL"


def test_forbidden_phrase_fails():
    turns = [Turn(say="cho tôi lịch xe"), Turn(say="giá bao nhiêu")]  # mock trả giá ở lượt 2
    result = _run(_scenario("forbidden.yaml", turns, forbidden=("350.000đ",)))
    assert result.status == "FAIL"
    assert any(c.name == "forbidden_phrase" and c.status == "FAIL" for c in result.checks)


def test_early_endcall_stops_and_fails():
    turns = [Turn(say=f"turn {i}") for i in range(6)]
    result = _run(_scenario("early.yaml", turns))
    assert result.status == "FAIL"
    early = next(c for c in result.checks if c.name == "call_ended_early")
    assert early.status == "FAIL" and "còn 2 lượt" in early.detail
    assert len(result.transcript) == 4  # dừng gửi sau |ENDCALL ở lượt thứ 4


def test_transport_error_blocks_without_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    dead = Target(
        name="dead",
        kind="sse_chat",
        base_url="http://localhost:1",
        init_path="/api/conversation/init",
    )
    scenario = _scenario("dead.yaml", [Turn(say="alô")])
    result = asyncio.run(
        run_scenario(dead, scenario, transport=httpx.MockTransport(handler))
    )
    assert result.status == "BLOCKED"
    assert result.error is not None and "ConnectError" in result.error


def test_suite_writes_one_jsonl_line_per_scenario(tmp_path):
    from pathlib import Path

    from autoqa.config import load_config

    targets = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    scenarios = [
        _scenario("a.yaml", [Turn(say="t1")]),
        _scenario("b.yaml", [Turn(say="t1"), Turn(say="t2")]),
    ]
    out = tmp_path / "runs" / "run.jsonl"
    results = asyncio.run(
        run_suite(targets, scenarios, run_id="test-run", out_jsonl=out)
    )
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(results) == 2
    rows = [json.loads(line) for line in lines]
    assert all(row["run_id"] == "test-run" and row["target"] == "mock" for row in rows)
    assert all(row["status"] == "PASS" for row in rows)
    assert rows[0]["transcript"][0]["assistant"]  # có lời bot trong transcript


def test_suite_runs_concurrently_preserving_order(tmp_path):
    from autoqa.config import load_config

    targets = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    scenarios = [_scenario(f"c{i}.yaml", [Turn(say=f"turn {j}") for j in range(2)]) for i in range(5)]
    out = tmp_path / "run.jsonl"
    results = asyncio.run(
        run_suite(targets, scenarios, run_id="conc", out_jsonl=out, concurrency=3)
    )
    assert [r.id for r in results] == [s.id for s in scenarios]  # thứ tự khai báo
    assert all(r.status == "PASS" and r.target_name == "mock" for r in results)
    assert len(out.read_text(encoding="utf-8").strip().splitlines()) == 5
