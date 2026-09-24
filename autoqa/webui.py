"""Web UI mỏng cho auto-qa — chạy test từ trình duyệt, xem transcript, tra conv ID.

Lớp MỎNG trên các hàm core có sẵn (load_suite, run_suite, write_report,
_append_index từ cli): không đẻ logic nghiệp vụ thứ hai. Không có LLM review.
`bots/*/raw/` không bao giờ được serve — chỉ knowledge + scenarios + profile.

Bảo mật: env AUTOQA_UI_KEY đặt thì mọi /api/* yêu cầu header X-API-Key khớp;
bỏ trống = chế độ dev nội bộ (chỉ chạy khi tin cậy mạng).

Chạy local:  python -m autoqa ui
Deploy:      docker compose up -d  (xem PLAN-UI-DEPLOY.md)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from autoqa.cli import _append_index
from autoqa.config import ConfigError, load_config
from autoqa.llm import LlmError, build_llm_caller, load_dotenv
from autoqa.report import write_report
from autoqa.runner import run_suite
from autoqa.scenario import ScenarioError, load_scenario

_BOT_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
_STATIC_DIR = Path(__file__).parent / "static"


@dataclass
class JobState:
    run_id: str
    bot: str
    total: int
    status: str = "running"  # running | done | error
    error: str | None = None
    results: list[dict] = field(default_factory=list)


def _bot_dir(bots_dir: Path, bot: str) -> Path:
    if not _BOT_NAME_RE.match(bot):
        raise HTTPException(400, f"tên bot không hợp lệ: {bot!r}")
    d = bots_dir / bot
    if not (d / "profile.yaml").is_file():
        raise HTTPException(404, f"không có bot {bot!r} (thiếu profile.yaml)")
    return d


def _check_key(request) -> None:
    key = os.environ.get("AUTOQA_UI_KEY", "")
    if not key:
        return  # chế độ dev nội bộ — không expose khi bỏ trống key
    if request.headers.get("X-API-Key") != key:
        raise HTTPException(401, "thiếu hoặc sai X-API-Key")


def _read_run_rows(runs_dir: Path, run_id: str) -> list[dict]:
    path = runs_dir / f"{run_id}.jsonl"
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


def create_app(*, bots_dir="bots", runs_dir="runs", config_path="config.yaml") -> FastAPI:
    bots_dir, runs_dir = Path(bots_dir), Path(runs_dir)
    app = FastAPI(title="auto-qa", docs_url=None, redoc_url=None)
    app.state.jobs: dict[str, JobState] = {}
    app.state.run_lock = asyncio.Lock()

    # ---------- bots (đọc) ----------

    @app.get("/api/bots")
    def list_bots(request: Request) -> list[dict]:
        _check_key(request)
        out = []
        if not bots_dir.is_dir():
            return out
        for d in sorted(bots_dir.iterdir()):
            if not d.is_dir() or not (d / "profile.yaml").is_file():
                continue
            prof = yaml.safe_load((d / "profile.yaml").read_text(encoding="utf-8")) or {}
            n, n_llm = 0, 0
            for f in (
                sorted((d / "scenarios").glob("*.yaml")) if (d / "scenarios").is_dir() else []
            ):
                try:
                    s = load_scenario(f)
                except ScenarioError:
                    continue  # kịch bản lỗi hiện ở endpoint chi tiết, không chặn listing
                n += 1
                n_llm += s.mode == "llm"
            out.append(
                {
                    "bot": d.name,
                    "display_name": str(prof.get("display_name") or d.name),
                    "profile_target": str(prof.get("target") or ""),
                    "n_scenarios": n,
                    "n_llm": n_llm,
                }
            )
        return out

    @app.get("/api/bots/{bot}/scenarios")
    def bot_scenarios(bot: str, request: Request) -> list[dict]:
        _check_key(request)
        d = _bot_dir(bots_dir, bot)
        sdir = d / "scenarios"
        out = []
        for f in sorted(sdir.glob("*.yaml")) if sdir.is_dir() else []:
            try:
                s = load_scenario(f)
            except ScenarioError as exc:
                out.append({"id": f.stem, "error": str(exc)})
                continue
            out.append(
                {
                    "id": s.id,
                    "mode": s.mode,
                    "target": s.target,
                    "turns": s.max_turns if s.mode == "llm" else len(s.turns),
                    "mix": list(s.mix),
                    "forbidden": list(s.forbidden_phrases),
                }
            )
        return out

    @app.get("/api/bots/{bot}/knowledge")
    def bot_knowledge(bot: str, request: Request) -> dict:
        _check_key(request)
        d = _bot_dir(bots_dir, bot)
        bfile = d / "knowledge" / "business.md"
        text = bfile.read_text(encoding="utf-8") if bfile.is_file() else ""
        return {
            "bot": bot,
            "business": text,
            "has_run_warning": "CẢNH BÁO KHI CHẠY TEST" in text,
        }

    @app.get("/api/targets")
    def targets(request: Request) -> list[dict]:
        _check_key(request)
        try:
            cfg = load_config(config_path)
        except (ConfigError, Exception) as exc:
            raise HTTPException(500, f"config lỗi: {exc}")
        return [{"name": t.name, "kind": t.kind} for t in cfg.values()]

    # ---------- chạy test (1 run cùng lúc) ----------

    async def _run_job(state: JobState, scenarios, targets, llm_caller, target_override, concurrency):
        try:
            results = await run_suite(
                targets,
                scenarios,
                run_id=state.run_id,
                target_override=target_override,
                bot_id=None,
                out_jsonl=runs_dir / f"{state.run_id}.jsonl",
                llm_caller=llm_caller,
                concurrency=concurrency,
            )
            write_report(results, runs_dir / f"{state.run_id}.md", run_id=state.run_id)
            _append_index(runs_dir, state.run_id, results, runs_dir / f"{state.run_id}.md")
            state.results = [
                {
                    "id": r.id,
                    "status": r.status,
                    "conversation_id": r.conversation_id,
                    "target": r.target_name,
                }
                for r in results
            ]
            state.status = "done"
        except Exception as exc:  # job nền không được giết app
            state.status = "error"
            state.error = f"{type(exc).__name__}: {exc}"
        finally:
            if llm_caller is not None:
                await llm_caller.aclose()

    async def _job_then_release(state, scenarios, targets, llm_caller, target_override, concurrency):
        try:
            await _run_job(state, scenarios, targets, llm_caller, target_override, concurrency)
        finally:
            app.state.run_lock.release()

    @app.post("/api/runs")
    async def start_run(body: dict, request: Request) -> dict:
        _check_key(request)
        bot = str(body.get("bot") or "")
        wanted = body.get("scenarios") or []
        target_override = body.get("target") or None
        concurrency = max(1, min(int(body.get("concurrency") or 1), 4))
        if not isinstance(wanted, list) or not wanted:
            raise HTTPException(400, "cần danh sách 'scenarios' (id kịch bản)")

        d = _bot_dir(bots_dir, bot)
        suite: dict[str, object] = {}
        sdir = d / "scenarios"
        for f in sorted(sdir.glob("*.yaml")) if sdir.is_dir() else []:
            try:
                s = load_scenario(f)
                suite[s.id] = s
            except ScenarioError:
                continue
        unknown = [w for w in wanted if w not in suite]
        if unknown:
            raise HTTPException(400, f"không có kịch bản: {', '.join(unknown)}")
        scenarios = [suite[w] for w in wanted]

        if app.state.run_lock.locked():
            raise HTTPException(409, "đang có run khác chạy — chờ xong rồi chạy tiếp")

        load_dotenv()
        try:
            targets = load_config(config_path)
            llm_caller = build_llm_caller(config_path, scenarios)
        except (LlmError, ConfigError) as exc:
            raise HTTPException(400, f"không dựng được run: {exc}")

        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        state = JobState(run_id=run_id, bot=bot, total=len(scenarios))
        app.state.jobs[run_id] = state
        await app.state.run_lock.acquire()
        app.state.current_task = asyncio.create_task(
            _job_then_release(state, scenarios, targets, llm_caller, target_override, concurrency)
        )
        return {"run_id": run_id, "total": state.total, "status_url": f"/api/runs/{run_id}/status"}

    @app.get("/api/runs/{run_id}/status")
    def run_status(run_id: str, request: Request) -> dict:
        _check_key(request)
        state = app.state.jobs.get(run_id)
        if state is not None:
            done = len(_read_run_rows(runs_dir, run_id))  # mỗi kịch bản xong = 1 dòng JSONL
            return {
                "run_id": run_id,
                "status": state.status,
                "done": done if state.status == "running" else state.total,
                "total": state.total,
                "error": state.error,
                "results": state.results,
            }
        if (runs_dir / f"{run_id}.jsonl").is_file():  # run từ lần chạy trước (sau restart)
            return {"run_id": run_id, "status": "done", "results": []}
        raise HTTPException(404, f"không có run {run_id}")

    # ---------- lịch sử & chi tiết ----------

    @app.get("/api/runs")
    def list_runs(request: Request) -> list[dict]:
        _check_key(request)
        index = runs_dir / "INDEX.md"
        if not index.is_file():
            return []
        out = []
        for line in index.read_text(encoding="utf-8").splitlines():
            parts = [p.strip() for p in line.strip().strip("|").split("|")]
            if len(parts) != 6 or parts[0] in ("Run", "---"):
                continue
            out.append(
                {
                    "run": parts[0],
                    "target": parts[1],
                    "scenario": parts[2].strip("`"),
                    "status": parts[3],
                    "conversation": parts[4],
                    "report": parts[5],
                }
            )
        return list(reversed(out))

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str, request: Request) -> dict:
        _check_key(request)
        if not re.match(r"^\d{8}-\d{6}$", run_id):
            raise HTTPException(400, "run_id không hợp lệ")
        rows = _read_run_rows(runs_dir, run_id)
        if not rows:
            raise HTTPException(404, f"không có run {run_id}")
        return {
            "run_id": run_id,
            "report_exists": (runs_dir / f"{run_id}.md").is_file(),
            "scenarios": rows,
        }

    # ---------- static ----------

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    return app
