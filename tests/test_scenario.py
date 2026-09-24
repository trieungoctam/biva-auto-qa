import pytest

from autoqa.scenario import ScenarioError, load_scenario, load_suite


def _valid() -> dict:
    return {
        "suite": "s",
        "name": "n",
        "target": "mock",
        "turns": [{"say": "alô", "expect": {"tag": "CHAT"}}],
    }


def test_load_valid_scenario_with_defaults(yaml_file):
    raw = _valid()
    raw.pop("suite")
    path = yaml_file("my-suite.yaml", raw)
    scenario = load_scenario(path)
    assert scenario.suite == "my-suite"  # suite mặc định lấy từ tên file
    assert scenario.name == "n"
    assert scenario.turns[0].expect.tag == "CHAT"
    assert scenario.turns[0].expect.reply_nonempty is True


def test_turn_without_say_rejected_with_path_context(yaml_file):
    path = yaml_file("bad.yaml", {"target": "mock", "turns": [{"expect": {}}]})
    with pytest.raises(ScenarioError, match=str(path)):
        load_scenario(path)


def test_invalid_tag_rejected(yaml_file):
    path = yaml_file("bad.yaml", {"target": "mock", "turns": [{"say": "a", "expect": {"tag": "WAVE"}}]})
    with pytest.raises(ScenarioError, match="ENDCALL"):
        load_scenario(path)


def test_empty_turns_rejected(yaml_file):
    path = yaml_file("bad.yaml", {"target": "mock", "turns": []})
    with pytest.raises(ScenarioError, match="turns"):
        load_scenario(path)


def test_load_suite_requires_matches(tmp_path):
    with pytest.raises(ScenarioError, match="không có kịch bản"):
        load_suite(tmp_path / "nothing-*.yaml")
