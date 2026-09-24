from pathlib import Path

import yaml

from autoqa.cli import main


def _write(dir_path: Path, name: str, data: dict) -> Path:
    path = dir_path / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _mock_config(tmp_path: Path) -> Path:
    return _write(tmp_path, "config.yaml", {"targets": [{"name": "mock", "kind": "mock"}]})


def _suite_dir(tmp_path: Path) -> Path:
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir(exist_ok=True)
    return suite_dir


def test_cli_exit_zero_and_writes_artifacts(tmp_path, capsys):
    config = _mock_config(tmp_path)
    suite_dir = _suite_dir(tmp_path)
    _write(
        suite_dir,
        "ok.yaml",
        {"suite": "t", "name": "ok", "target": "mock", "turns": [{"say": f"turn {i}"} for i in range(4)]},
    )
    out = tmp_path / "runs"
    code = main(["run", "--suite", str(suite_dir / "*.yaml"), "--config", str(config), "--out", str(out)])
    assert code == 0
    artifacts = list(out.iterdir())
    assert {p.suffix for p in artifacts} == {".jsonl", ".md"}
    report = next(p for p in artifacts if p.suffix == ".md" and p.name != "INDEX.md").read_text(encoding="utf-8")
    assert "`t/ok`" in report and "**PASS**" in report
    index = (out / "INDEX.md").read_text(encoding="utf-8")   # mỗi run lưu chỉ mục để tra conversation_id
    assert "| PASS |" in index and "`t/ok`" in index and "runs" in index
    assert "PASS" in capsys.readouterr().out


def test_cli_failing_suite_exits_one(tmp_path):
    config = _mock_config(tmp_path)
    suite_dir = _suite_dir(tmp_path)
    _write(
        suite_dir,
        "fail.yaml",
        {
            "suite": "t",
            "name": "fail",
            "target": "mock",
            "forbidden_phrases": ["350.000đ"],
            "turns": [{"say": "cho tôi lịch xe"}, {"say": "giá bao nhiêu"}],
        },
    )
    code = main(
        ["run", "--suite", str(suite_dir / "*.yaml"), "--config", str(config), "--out", str(tmp_path)]
    )
    assert code == 1


def test_cli_target_override_uses_named_target(tmp_path):
    config = _write(
        tmp_path,
        "config.yaml",
        {"targets": [{"name": "mock", "kind": "mock"}, {"name": "alias", "kind": "mock"}]},
    )
    suite_dir = _suite_dir(tmp_path)
    _write(
        suite_dir,
        "a.yaml",
        {"suite": "t", "name": "a", "target": "mock", "turns": [{"say": "x"}]},
    )
    code = main(
        [
            "run",
            "--suite",
            str(suite_dir / "*.yaml"),
            "--config",
            str(config),
            "--out",
            str(tmp_path),
            "--target",
            "alias",
        ]
    )
    assert code == 0
    jsonl = next(p for p in tmp_path.iterdir() if p.suffix == ".jsonl")
    row = jsonl.read_text(encoding="utf-8").strip().splitlines()[0]
    assert '"target": "alias"' in row


def test_cli_bot_id_without_target_rejected(tmp_path, capsys):
    config = _mock_config(tmp_path)
    suite_dir = _suite_dir(tmp_path)
    _write(suite_dir, "a.yaml", {"suite": "t", "name": "a", "target": "mock", "turns": [{"say": "x"}]})
    code = main(
        ["run", "--suite", str(suite_dir / "*.yaml"), "--config", str(config), "--bot-id", "3"]
    )
    assert code == 2
    assert "--bot-id" in capsys.readouterr().out
