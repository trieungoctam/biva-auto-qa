from pathlib import Path

import pytest
import yaml

from autoqa.scenario import ScenarioError, load_scenario


def _project(tmp_path: Path, profile_extra: dict | None = None) -> Path:
    """bots/botx/ với knowledge/business.md + profile.yaml; trả về root bot."""
    root = tmp_path / "bots" / "botx"
    (root / "knowledge").mkdir(parents=True)
    (root / "knowledge" / "business.md").write_text(
        "nghiệp vụ nền bot X\n- quy tắc chung", encoding="utf-8"
    )
    profile = {
        "bot": "botx",
        "target": "botx-conn",
        "business_file": "knowledge/business.md",
        "defaults": {"max_turns": 6, "persona": {"phone": "0987654321"}},
    }
    if profile_extra:
        # giá trị None = xoá key khỏi profile cơ sở
        for k, v in profile_extra.items():
            if v is None:
                profile.pop(k, None)
            else:
                profile[k] = v
    (root / "profile.yaml").write_text(yaml.safe_dump(profile, allow_unicode=True), encoding="utf-8")
    (root / "scenarios").mkdir()
    (root / "knowledge" / "call-scripts").mkdir(exist_ok=True)
    return root


def _scenario(root: Path, name: str, data: dict) -> Path:
    sc_path = root / "scenarios" / f"{name}.yaml"
    sc_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return sc_path


def _llm_scenario(name: str, **extra) -> dict:
    data = {
        "mode": "llm",
        "suite": "s",
        "name": name,
        "profile": "botx",
        "goal": "hỏi giá",
        "context": "- luật riêng",
        "persona": {"style": "nói ngắn"},
    }
    data.update(extra)
    return data


def test_scenario_inherits_profile_business_file_and_defaults(tmp_path):
    root = _project(tmp_path)
    sc = load_scenario(_scenario(root, "g", _llm_scenario("g")))
    assert sc.target == "botx-conn"            # target từ profile
    assert sc.max_turns == 6                    # defaults từ profile
    assert sc.persona == {"phone": "0987654321", "style": "nói ngắn"}  # gộp, kịch bản thắng
    assert "nghiệp vụ nền bot X" in sc.effective_context and "luật riêng" in sc.effective_context
    assert sc.business != sc.effective_context  # business giữ riêng, effective gộp


def test_scenario_declared_fields_override_profile(tmp_path):
    root = _project(tmp_path)
    sc = load_scenario(
        _scenario(root, "g2", _llm_scenario("g2", target="khac", max_turns=3, context=""))
    )
    assert sc.target == "khac" and sc.max_turns == 3


def test_inline_business_instead_of_file(tmp_path):
    root = _project(tmp_path, profile_extra={"business": "nghiệp vụ inline", "business_file": None})
    sc = load_scenario(_scenario(root, "g", _llm_scenario("g")))
    assert "nghiệp vụ inline" in sc.effective_context


def test_business_and_business_file_are_exclusive(tmp_path):
    root = _project(
        tmp_path,
        profile_extra={"business": "inline", "business_file": "knowledge/business.md"},
    )
    with pytest.raises(ScenarioError, match="MỘT trong"):
        load_scenario(_scenario(root, "g", _llm_scenario("g")))


def test_missing_business_file_raises(tmp_path):
    root = _project(tmp_path, profile_extra={"business_file": "knowledge/khong-co.md"})
    with pytest.raises(ScenarioError, match="business_file"):
        load_scenario(_scenario(root, "g", _llm_scenario("g")))


def test_profile_name_mismatch_raises(tmp_path):
    root = _project(tmp_path)
    sc_path = _scenario(root, "g", _llm_scenario("g", profile="botkhac"))
    with pytest.raises(ScenarioError, match="là của bot"):
        load_scenario(sc_path)


def test_missing_profile_raises(tmp_path):
    root = _project(tmp_path)
    sc_path = _scenario(root, "bad", _llm_scenario("bad", profile="khong-co"))
    (root / "profile.yaml").unlink()
    with pytest.raises(ScenarioError, match="không thấy profile.yaml"):
        load_scenario(sc_path)


def test_scenario_auto_inherits_profile_without_declaring(tmp_path):
    """Kịch bản nằm dưới profile.yaml thì tự kế thừa, không cần khai profile:."""
    root = _project(tmp_path)
    data = _llm_scenario("g3")
    data.pop("profile")
    sc = load_scenario(_scenario(root, "g3", data))
    assert sc.target == "botx-conn"
    assert sc.profile is None and sc.max_turns == 6
    assert "nghiệp vụ nền bot X" in sc.effective_context


def _situation(root: Path, name: str, data: dict) -> Path:
    situations = root / "situations"
    situations.mkdir(exist_ok=True)
    path = situations / f"{name}.yaml"
    path.write_text(yaml.safe_dump({"name": name, **data}, allow_unicode=True), encoding="utf-8")
    return path


def test_mix_merges_situations_into_one_call(tmp_path):
    root = _project(tmp_path)
    _situation(
        root, "tre-em",
        {
            "goal": "Có thêm một trẻ em đi cùng; hỏi chiều cao bé.",
            "context": "- Bé 1m2 → phải báo phụ thu 150.000đ.",
            "persona": {"style": "lo lắng cho con"},
            "forbidden_phrases": ["miễn phí cho bé", "không tính tiền bé"],
            "extra_turns": 3,
        },
    )
    _situation(root, "doi-y", {"goal": "Giữa chừng đổi ý muốn chọn ngày khác."})
    sc = load_scenario(
        _scenario(
            root, "mix",
            _llm_scenario("mix", mix=["tre-em", "doi-y"], max_turns=10, forbidden_phrases=["máy bay"]),
        )
    )
    assert "[tre-em]" in sc.goal and "trẻ em đi cùng" in sc.goal
    assert "[doi-y]" in sc.goal and "đổi ý" in sc.goal
    assert "Luật từ tình huống [tre-em]" in sc.context and "phụ thu 150.000đ" in sc.context
    assert sc.forbidden_phrases == ("máy bay", "miễn phí cho bé", "không tính tiền bé")
    assert sc.persona["style"] == "lo lắng cho con"            # tình huống thắng key trùng
    assert sc.persona["phone"] == "0987654321"                  # persona gốc giữ nguyên
    assert sc.max_turns == 13                                   # 10 + extra_turns 3


def test_mix_unknown_situation_raises(tmp_path):
    root = _project(tmp_path)
    with pytest.raises(ScenarioError, match="mix 'khong-ton-tai'"):
        load_scenario(_scenario(root, "m", _llm_scenario("m", mix=["khong-ton-tai"])))


def test_mix_requires_situations_dir(tmp_path):
    root = _project(tmp_path)
    (root / "situations").mkdir(exist_ok=True)
    (root / "situations" / "ok.yaml").write_text("name: ok\n", encoding="utf-8")
    sc = load_scenario(_scenario(root, "m", _llm_scenario("m", mix=["ok"])))
    assert "[ok]" not in sc.goal  # tình huống không có goal → không nối mục tiêu


def test_mix_rejected_in_script_mode(tmp_path):
    root = _project(tmp_path)
    with pytest.raises(ScenarioError, match="'mix' chỉ dùng cho mode llm"):
        load_scenario(
            _scenario(
                root,
                "s",
                {
                    "mode": "script",
                    "suite": "s",
                    "name": "s",
                    "target": "botx-conn",
                    "mix": ["tre-em"],
                    "turns": [{"say": "hi"}],
                },
            )
        )


def test_profile_call_scripts_dir_expands_txt_files(tmp_path):
    root = _project(tmp_path)
    scripts = root / "knowledge" / "call-scripts"
    (scripts / "02-later.txt").write_text("Khách: B\nTổng đài: Dạ B\n", encoding="utf-8")
    (scripts / "01-early.txt").write_text("Khách: A lô chị ơi\nTổng đài: Dạ em xin nghe ạ\n", encoding="utf-8")
    (root / "profile.yaml").unlink()
    profile = {
        "bot": "botx",
        "target": "botx-conn",
        "business": "nghiệp vụ nền",
        "defaults": {"max_turns": 6},
        "call_scripts": ["knowledge/call-scripts"],
    }
    (root / "profile.yaml").write_text(yaml.safe_dump(profile, allow_unicode=True), encoding="utf-8")
    sc = load_scenario(_scenario(root, "g", _llm_scenario("g")))
    assert sc.call_scripts[0].startswith("Khách: A lô chị ơi")   # sắp theo tên file
    assert sc.call_scripts[1].startswith("Khách: B")
