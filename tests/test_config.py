import pytest

from autoqa.config import ConfigError, load_config, resolve_target


def test_load_repo_config_has_mock_and_live_demo(mock_targets):
    assert set(mock_targets) >= {"mock", "live-demo"}
    live = mock_targets["live-demo"]
    assert live.init_path == "/api/conversation/init"
    assert live.chat_path == "/chat/stream"
    assert live.base_url == "https://live-demo.agenticai.pro.vn"


def test_sse_target_requires_base_url_and_init(yaml_file):
    path = yaml_file(
        "bad.yaml",
        {"targets": [{"name": "x", "kind": "sse_chat", "base_url": "http://x"}]},
    )
    with pytest.raises(ConfigError, match="init_path"):
        load_config(path)


def test_unknown_kind_rejected(yaml_file):
    path = yaml_file("bad.yaml", {"targets": [{"name": "x", "kind": "carrier-pigeon"}]})
    with pytest.raises(ConfigError, match="không hỗ trợ"):
        load_config(path)


def test_missing_config_file():
    with pytest.raises(ConfigError, match="không tìm thấy"):
        load_config("nope/missing.yaml")


def test_resolve_unknown_target_lists_known(mock_targets):
    with pytest.raises(ConfigError, match="mock"):
        resolve_target(mock_targets, "khong-ton-tai")
