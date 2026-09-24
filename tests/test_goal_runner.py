import asyncio
from pathlib import Path

import pytest

from autoqa.config import load_config, ConfigError
from autoqa.llm import LlmError
from autoqa.runner import run_goal_scenario, run_scenario, run_suite
from autoqa.scenario import ScenarioError, load_scenario

REPO = Path(__file__).resolve().parents[1]


class FakeLlm:
    """LLLM giả theo hàng đợi: mỗi phần tử là dict phản hồi hoặc exception để ném."""

    def __init__(self, responses: list):
        self._queue = list(responses)
        self.prompts: list[str] = []

    async def chat_json(self, system: str, user: str) -> dict:
        self.prompts.append(system)
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _goal_yaml(tmp_path: Path, **overrides) -> Path:
    import yaml

    data = {
        "mode": "llm",
        "suite": "g",
        "name": "goal",
        "target": "mock",
        "persona": {"name": "anh Tâm", "phone": "0987654321"},
        "goal": "Hỏi giá rồi đặt một vé",
        "max_turns": 4,
        "context": "Bot phải đọc giờ đầy đủ.",
    }
    data.update(overrides)
    path = tmp_path / "goal.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _run(scenario, llm):
    targets = load_config(REPO / "config.yaml")
    return asyncio.run(run_goal_scenario(targets["mock"], scenario, llm))


def _say(say: str, done: bool = False, note: str = "") -> dict:
    return {"say": say, "done": done, "note": note}


def test_goal_completed_after_exchange_passes(tmp_path):
    scenario = load_scenario(_goal_yaml(tmp_path))
    llm = FakeLlm([
        _say("Chị ơi tối mai còn xe đi Đà Lạt không?"),
        _say("Vậy đặt giúp em một vé"),
        _say("", done=True, note="đã xác nhận đặt vé"),
    ])
    result = _run(scenario, llm)
    assert result.status == "PASS"
    assert [c.name for c in result.checks if c.name == "goal_completed"]
    assert len(result.transcript) == 2
    assert result.transcript[0]["caller_note"] == ""


def test_max_turns_exhausted_fails(tmp_path):
    scenario = load_scenario(_goal_yaml(tmp_path, max_turns=2))
    llm = FakeLlm([
        _say("hỏi 1"),
        _say("hỏi 2"),
    ])
    result = _run(scenario, llm)
    assert result.status == "FAIL"
    assert any(c.name == "goal_not_completed" and c.status == "FAIL" for c in result.checks)
    assert len(result.transcript) == 2


def test_bot_endcall_before_goal_fails(tmp_path):
    # mock bot |ENDCALL ở lượt khách thứ 4; caller vẫn chưa done
    scenario = load_scenario(_goal_yaml(tmp_path, max_turns=8))
    llm = FakeLlm([_say(f"lượt {i}") for i in range(8)])
    result = _run(scenario, llm)
    assert result.status == "FAIL"
    assert any(c.name == "call_ended_early" for c in result.checks)
    assert len(result.transcript) == 4  # driver dừng gửi sau |ENDCALL


def test_llm_error_blocks(tmp_path):
    scenario = load_scenario(_goal_yaml(tmp_path))
    llm = FakeLlm([LlmError("thiếu biến môi trường OPENAI_API_KEY")])
    result = _run(scenario, llm)
    assert result.status == "BLOCKED"
    assert result.error is not None and "OPENAI_API_KEY" in result.error


def test_run_suite_without_llm_config_raises(tmp_path):
    scenario = load_scenario(_goal_yaml(tmp_path))
    with pytest.raises(ConfigError, match="llm"):
        asyncio.run(run_suite(load_config(REPO / "config.yaml"), [scenario], run_id="t"))


# --- schema mode llm ---

def test_llm_mode_requires_goal_and_max_turns(yaml_file):
    with pytest.raises(ScenarioError, match="goal"):
        load_scenario(yaml_file("a.yaml", {"mode": "llm", "target": "mock", "max_turns": 4}))
    with pytest.raises(ScenarioError, match="max_turns"):
        load_scenario(yaml_file("a.yaml", {"mode": "llm", "target": "mock", "goal": "đặt vé"}))


def test_llm_mode_rejects_fixed_turns(yaml_file):
    path = yaml_file(
        "a.yaml", {"mode": "llm", "target": "mock", "goal": "g", "max_turns": 4, "turns": [{"say": "x"}]}
    )
    with pytest.raises(ScenarioError, match="không dùng 'turns'"):
        load_scenario(path)


def test_call_scripts_resolved_from_file(tmp_path, yaml_file):
    script = tmp_path / "call-01.txt"
    script.write_text("Khách: A lô chị ơi\nTổng đài: Dạ em xin nghe ạ\n", encoding="utf-8")
    path = yaml_file(
        "a.yaml",
        {
            "mode": "llm",
            "target": "mock",
            "goal": "đặt vé",
            "max_turns": 4,
            "call_scripts": ["call-01.txt", "khách nói vặt inline"],
        },
    )
    scenario = load_scenario(path)
    assert scenario.call_scripts[0].startswith("Khách: A lô chị ơi")
    assert scenario.call_scripts[1] == "khách nói vặt inline"


def test_dispatch_by_mode(tmp_path):
    scenario = load_scenario(_goal_yaml(tmp_path))
    with pytest.raises(ConfigError):
        asyncio.run(
            run_scenario(load_config(REPO / "config.yaml")["mock"], scenario, llm_caller=None)
        )


def test_caller_only_llm_role_per_turn(tmp_path):
    """Duy nhất caller LLM được gọi, đúng một lần mỗi lượt khách."""
    scenario = load_scenario(_goal_yaml(tmp_path))
    llm = FakeLlm([
        _say("Chị ơi còn xe tối mai không ạ?"),
        _say("", done=True, note="đủ thông tin"),
    ])
    targets = load_config(REPO / "config.yaml")
    result = asyncio.run(run_goal_scenario(targets["mock"], scenario, llm))
    assert result.status == "PASS"
    assert len(llm.prompts) == 2 and all("KHÁCH HÀNG" in p for p in llm.prompts)
