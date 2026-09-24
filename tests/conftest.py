from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def yaml_file(tmp_path: Path):
    """Factory ghi dict ra file YAML trong tmp, trả về path."""

    def _write(name: str, data: dict) -> Path:
        path = tmp_path / name
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def mock_targets():
    from autoqa.config import load_config

    return load_config(REPO_ROOT / "config.yaml")
