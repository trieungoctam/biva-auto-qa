"""Git audit cho lần sửa từ UI — commit (và push nếu bật) sau mỗi thay đổi dữ liệu.

Server chạy trong repo git (deploy bằng git clone, mount .git rw). Nếu không có
.git hoặc git lỗi → im lặng bỏ qua: chỉnh sửa vẫn lưu, chỉ thiếu vết audit.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=30
    )


def commit_paths(repo_dir: Path, paths: list[Path], *, author: str, message: str) -> str | None:
    """Commit các path (tương đối repo) với author tên người dùng UI.

    Trả về hash ngắn nếu commit được; None nếu không có git/không đổi gì/lỗi.
    """
    repo_dir = Path(repo_dir)
    if not (repo_dir / ".git").exists():
        return None
    try:
        rel = [str(p.resolve().relative_to(repo_dir.resolve())) for p in paths]
    except ValueError:
        return None  # file nằm ngoài repo (vd tmp) — không audit được
    ident = ["-c", f"user.name={author}", "-c", "user.email={author}@auto-qa.local"]
    add = _run_git(repo_dir, *ident, "add", "--", *rel)
    if add.returncode != 0:
        return None
    commit = _run_git(repo_dir, *ident, "commit", "-m", message, "--no-verify")
    if commit.returncode != 0:
        return None  # không có gì đổi
    if os.environ.get("AUTOQA_GIT_PUSH", "") == "1":
        _run_git(repo_dir, "push", "--quiet")  # best-effort
    out = _run_git(repo_dir, "rev-parse", "--short", "HEAD")
    return out.stdout.strip() if out.returncode == 0 else None


def atomic_write(path: Path, content: str) -> None:
    """Ghi tạm rồi rename — crash giữa chừng không để file nửa vời."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
