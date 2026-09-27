"""Web UI auto-qa — sản phẩm nội bộ cho team (đợt v1: M1+M2 theo docs/TECH-DESIGN.md).

Lớp MỎNG trên các hàm core có sẵn (load_suite, run_suite, write_report,
_append_index): không đẻ logic nghiệp vụ thứ hai. Không có LLM review.
`bots/*/raw/` không bao giờ được serve.

Người dùng: `users.yaml` (key SHA-256, role admin/member) — thêm/xoá/xoay qua UI
admin; admin đầu tiên bootstrap từ env AUTOQA_ADMIN_KEY. Store rỗng + không env =
chế độ dev nội bộ (user "dev", role admin).

Chạy local:  python -m autoqa ui
Deploy:      docker compose up -d (xem docs/RUNBOOK.md)
"""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from autoqa.cli import _append_index
from autoqa.config import ConfigError, load_config
from autoqa.llm import LlmError, build_llm_caller, load_dotenv
from autoqa.report import write_report
from autoqa.runner import run_suite
from autoqa.scenario import ScenarioError, load_scenario
from autoqa.db import Db
from autoqa.users import DbUserStore, UserStore, UsersError

_BOT_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
_RUN_ID_RE = re.compile(r"^\d{8}-\d{6}(-\d+)?$")
_VERDICTS = ("ok", "issue", "warn")
_STATIC_DIR = Path(__file__).parent / "static"
MAX_CALLS_PER_RUN = 20


@dataclass
class JobState:
    run_id: str
    bot: str
    user: str
    total: int  # tổng calls (kịch bản × calls)
    status: str = "queued"  # queued | running | done | error
    error: str | None = None
    results: list[dict] = field(default_factory=list)


@dataclass
class QueueItem:
    state: JobState
    scenarios: list
    targets: dict
    llm_caller: "LlmClient | None"
    target_override: str | None
    concurrency: int
    calls: int


def _bot_dir(bots_dir: Path, bot: str) -> Path:
    if not _BOT_NAME_RE.match(bot):
        raise HTTPException(400, f"tên bot không hợp lệ: {bot!r}")
    d = bots_dir / bot
    if not (d / "profile.yaml").is_file():
        raise HTTPException(404, f"không có bot {bot!r} (thiếu profile.yaml)")
    return d


def _load_bot_scenarios(bots_dir: Path, bot: str) -> dict:
    d = _bot_dir(bots_dir, bot)
    sdir = d / "scenarios"
    suite: dict[str, object] = {}
    for f in sorted(sdir.glob("*.yaml")) if sdir.is_dir() else []:
        try:
            s = load_scenario(f)
            suite[s.id] = s
        except ScenarioError:
            continue
    return suite


def _read_run_rows(runs_dir: Path, run_id: str) -> list[dict]:
    path = runs_dir / f"{run_id}.jsonl"
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


def _review_path(runs_dir: Path, run_id: str) -> Path:
    return runs_dir / f"{run_id}.review.yaml"


def _load_reviews(runs_dir: Path, run_id: str) -> list[dict]:
    p = _review_path(runs_dir, run_id)
    if not p.is_file():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    return data if isinstance(data, list) else []


def _save_reviews(runs_dir: Path, run_id: str, reviews: list[dict]) -> None:
    _review_path(runs_dir, run_id).write_text(
        yaml.safe_dump(reviews, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def _parse_index(runs_dir: Path) -> list[dict]:
    index = runs_dir / "INDEX.md"
    if not index.is_file():
        return []
    out = []
    for line in index.read_text(encoding="utf-8").splitlines():
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) != 7 or parts[0] in ("Run", "---"):
            continue
        # ô kịch bản dạng: `suite/name` (2/3) → bỏ backtick, tách call
        scn_cell = parts[2].replace("`", "").strip()
        out.append(
            {
                "run": parts[0],
                "target": parts[1],
                "scenario": scn_cell,
                "status": parts[3],
                "conversation": parts[4],
                "user": parts[5],
                "report": parts[6],
            }
        )
    return out

def _sched_marker(runs_dir: Path, name: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    return runs_dir / f".sched-{safe}"


def _sched_due_today(s: dict, now: datetime) -> bool:
    """Đến giờ chạy trong ngày chưa (HH:MM)."""
    try:
        hh, mm = (int(x) for x in str(s.get("at", "")).split(":"))
    except ValueError:
        return False
    return now.hour * 60 + now.minute >= hh * 60 + mm


def create_app(
    *,
    bots_dir="bots",
    runs_dir="runs",
    config_path="config.yaml",
    users_file="users.yaml",
    schedules_file="schedules.yaml",
    db: Db | None = None,
) -> FastAPI:
    bots_dir, runs_dir = Path(bots_dir), Path(runs_dir)
    users_file, schedules_file = Path(users_file), Path(schedules_file)

    # ---------- vòng đời: queue worker + scheduler ----------

    async def _run_item(item: QueueItem) -> None:
        st = item.state
        st.status = "running"
        try:
            results = await run_suite(
                item.targets,
                item.scenarios,
                run_id=st.run_id,
                target_override=item.target_override,
                bot_id=None,
                out_jsonl=runs_dir / f"{st.run_id}.jsonl",
                llm_caller=item.llm_caller,
                concurrency=item.concurrency,
                calls=item.calls,
            )
            report_path = runs_dir / f"{st.run_id}.md"
            write_report(results, report_path, run_id=st.run_id)
            _append_index(runs_dir, st.run_id, results, report_path, user=st.user)
            if app.state.db.enabled:
                app.state.db.maybe(
                    app.state.db.push_run, st.run_id, _read_run_rows(runs_dir, st.run_id),
                    bot=st.bot, user=st.user,
                )
            st.results = [
                {
                    "id": r.id,
                    "call": f"{r.call_index}/{r.calls}" if r.calls > 1 else "",
                    "status": r.status,
                    "conversation_id": r.conversation_id,
                    "target": r.target_name,
                }
                for r in results
            ]
            st.status = "done"
        except Exception as exc:  # job nền không được giết app
            st.status = "error"
            st.error = f"{type(exc).__name__}: {exc}"
        finally:
            if item.llm_caller is not None:
                await item.llm_caller.aclose()

    async def _worker(app: FastAPI) -> None:
        while True:
            item: QueueItem = await app.state.queue.get()
            app.state.pending.discard(item.state.run_id)
            try:
                await _run_item(item)
            finally:
                app.state.queue.task_done()


    async def _scheduler(app: FastAPI) -> None:
        """Đọc schedules.yaml mỗi phút; đến giờ → enqueue run (user=scheduler)."""
        while True:
            try:
                if app.state.db.enabled:
                    scheds = [
                        {
                            "name": s.get("name"),
                            "bot": s.get("bot"),
                            "scenarios": s.get("scenarios") or [],
                            "at": s.get("at_time"),
                            "calls": s.get("calls") or 1,
                            "concurrency": s.get("concurrency") or 1,
                            "user": s.get("run_user") or "scheduler",
                        }
                        for s in (app.state.db.maybe(app.state.db.select, "aq_schedules") or [])
                    ]
                elif schedules_file.is_file():
                    scheds = yaml.safe_load(schedules_file.read_text(encoding="utf-8")) or []
                    now = datetime.now()
                    for s in scheds if isinstance(scheds, list) else []:
                        name = str(s.get("name") or s.get("bot") or "")
                        marker = _sched_marker(runs_dir, name)
                        ran_today = marker.is_file() and marker.read_text(encoding="utf-8").strip() == now.strftime("%Y-%m-%d")
                        if ran_today or not _sched_due_today(s, now):
                            continue
                        bot = str(s.get("bot") or "")
                        wanted = [str(w) for w in (s.get("scenarios") or [])]
                        try:
                            _enqueue_run(
                                app,
                                bot=bot,
                                wanted=wanted,
                                target_override=s.get("target") or None,
                                calls=int(s.get("calls") or 1),
                                concurrency=int(s.get("concurrency") or 1),
                                user=str(s.get("user") or "scheduler"),
                            )
                        except HTTPException:
                            pass  # schedule gõ sai — bỏ qua, chạy lại phút sau vẫn lỗi thì im
                        else:
                            marker.parent.mkdir(parents=True, exist_ok=True)
                            marker.write_text(now.strftime("%Y-%m-%d"), encoding="utf-8")
            except Exception:
                pass  # scheduler không bao giờ chết
            await asyncio.sleep(60)

    def _hydrate_bots_from_db() -> None:
        """Kéo aq_bots/scenarios/situations về file local (loader + git làm việc trên file)."""
        db = app.state.db
        if not db.enabled:
            return
        bots = db.maybe(db.select, "aq_bots") or []
        for b in bots:
            d = bots_dir / str(b.get("bot") or "")
            (d / "knowledge").mkdir(parents=True, exist_ok=True)
            (d / "scenarios").mkdir(exist_ok=True)
            (d / "situations").mkdir(exist_ok=True)
            if not (d / "profile.yaml").is_file():
                (d / "profile.yaml").write_text(
                    yaml.safe_dump(
                        {
                            "bot": b.get("bot"),
                            "display_name": b.get("display_name") or b.get("bot"),
                            "target": b.get("target") or "",
                            "business_file": "knowledge/business.md",
                        },
                        allow_unicode=True,
                    ),
                    encoding="utf-8",
                )
            if b.get("business"):
                atomic_write_local = d / "knowledge" / "business.md"
                atomic_write_local.write_text(str(b["business"]), encoding="utf-8")
            for table, folder in (("aq_scenarios", "scenarios"), ("aq_situations", "situations")):
                for row in db.maybe(db.select, table, {"bot": f"eq.{b.get('bot')}"}) or []:
                    (d / folder / f"{row['name']}.yaml").write_text(str(row.get("yaml") or ""), encoding="utf-8")

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        _hydrate_bots_from_db()
        app.state.users.bootstrap()
        app.state.worker = asyncio.create_task(_worker(app))
        app.state.sched_task = asyncio.create_task(_scheduler(app))
        yield
        app.state.worker.cancel()
        app.state.sched_task.cancel()

    app = FastAPI(title="auto-qa", docs_url=None, redoc_url=None, lifespan=_lifespan)
    app.state.db = db or Db()
    app.state.users = DbUserStore(app.state.db) if app.state.db.enabled else UserStore(users_file)
    app.state.jobs: dict[str, JobState] = {}
    app.state.queue: asyncio.Queue = asyncio.Queue()
    app.state.pending: set[str] = set()

    # ---------- auth ----------

    def _auth(request: Request) -> tuple[str, str]:
        """Xác thực qua users.yaml; store rỗng = dev mode (dev/admin)."""
        users: UserStore = app.state.users
        key = request.headers.get("X-API-Key", "")
        got = users.verify(key)
        if got:
            request.state.user_name, request.state.user_role = got
            return got
        if users.empty:
            request.state.user_name, request.state.user_role = "dev", "admin"
            return ("dev", "admin")
        raise HTTPException(401, "thiếu hoặc sai X-API-Key")

    def _admin(request: Request) -> tuple[str, str]:
        name, role = _auth(request)
        if role != "admin":
            raise HTTPException(403, "chỉ admin")
        return name, role

    # ---------- người dùng (admin) ----------

    @app.get("/api/me")
    def me(request: Request) -> dict:
        name, role = _auth(request)
        return {"name": name, "role": role}

    @app.get("/api/users")
    def list_users(request: Request) -> list[dict]:
        _admin(request)
        return app.state.users.listing()

    @app.post("/api/users")
    def add_user(body: dict, request: Request) -> dict:
        _admin(request)
        try:
            key = app.state.users.add(str(body.get("name") or ""), str(body.get("role") or "member"))
        except UsersError as exc:
            raise HTTPException(400, str(exc))
        return {"name": body.get("name"), "role": body.get("role"), "key": key}  # key hiện MỘT lần

    @app.post("/api/users/{name}/rotate")
    def rotate_user(name: str, request: Request) -> dict:
        try:
            key = app.state.users.rotate(name)
        except UsersError as exc:
            raise HTTPException(404, str(exc))
        return {"name": name, "key": key}

    @app.post("/api/users/{name}/role")
    def set_role(name: str, body: dict, request: Request) -> dict:
        _admin(request)
        try:
            app.state.users.set_role(name, str(body.get("role") or ""))
        except UsersError as exc:
            raise HTTPException(400, str(exc))
        return {"name": name, "role": body.get("role")}

    @app.delete("/api/users/{name}")
    def delete_user(name: str, request: Request) -> dict:
        _admin(request)
        try:
            app.state.users.delete(name)
        except UsersError as exc:
            raise HTTPException(404, str(exc))
        return {"ok": True}

    # ---------- bots (đọc) ----------

    @app.get("/api/bots")
    def list_bots(request: Request) -> list[dict]:
        _auth(request)
        out = []
        if not bots_dir.is_dir():
            return out
        for d in sorted(bots_dir.iterdir()):
            if not d.is_dir() or not (d / "profile.yaml").is_file():
                continue
            prof = yaml.safe_load((d / "profile.yaml").read_text(encoding="utf-8")) or {}
            n, n_llm = 0, 0
            sdir = d / "scenarios"
            for f in sorted(sdir.glob("*.yaml")) if sdir.is_dir() else []:
                try:
                    s = load_scenario(f)
                except ScenarioError:
                    continue
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
        _auth(request)
        _bot_dir(bots_dir, bot)
        sdir = _bot_dir(bots_dir, bot) / "scenarios"
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
        _auth(request)
        d = _bot_dir(bots_dir, bot)
        bfile = d / "knowledge" / "business.md"
        text = bfile.read_text(encoding="utf-8") if bfile.is_file() else ""
        return {"bot": bot, "business": text, "has_run_warning": "CẢNH BÁO KHI CHẠY TEST" in text}


    # ---------- chỉnh sửa dữ liệu bot (admin) — cloud là nguồn chân, git audit ----------

    _NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

    def _yaml_path(base: Path, name: str, kind: str) -> Path:
        if not _NAME_RE.match(name or ""):
            raise HTTPException(400, f"tên {kind} không hợp lệ (a-z, 0-9, gạch ngang)")
        return base / f"{name}.yaml"

    def _validate_scenario_yaml(path: Path) -> None:
        try:
            load_scenario(path)
        except ScenarioError as exc:
            raise HTTPException(400, f"YAML không hợp lệ: {exc}")

    def _commit(user: str, what: str, *paths: Path) -> str | None:
        from autoqa.audit import commit_paths

        return commit_paths(bots_dir.parent, list(paths), author=user, message=f"ui({user}): {what}")

    @app.put("/api/bots/{bot}/knowledge")
    def put_knowledge(bot: str, body: dict, request: Request) -> dict:
        name, _ = _admin(request)
        from autoqa.audit import atomic_write

        d = _bot_dir(bots_dir, bot)
        business = str(body.get("business") or "")
        if not business.strip():
            raise HTTPException(400, "business không được để trống")
        bfile = d / "knowledge" / "business.md"
        if app.state.db.enabled:
            prof = yaml.safe_load((d / "profile.yaml").read_text(encoding="utf-8")) or {}
            app.state.db.upsert(
                "aq_bots",
                {
                    "bot": bot,
                    "display_name": str(prof.get("display_name") or bot),
                    "target": str(prof.get("target") or ""),
                    "business": business,
                },
                "bot",
            )
        atomic_write(bfile, business)
        return {"ok": True, "commit": _commit(name, f"sửa knowledge {bot}", bfile)}

    def _source_crud(base: Path, kind: str, validate, name_check=None, db_table: str = "", bot: str = ""):
        """Factory cho GET/PUT/POST/DELETE nguồn YAML (scenarios | situations)."""

        def get_source(name: str, request: Request) -> dict:
            _auth(request)
            p = _yaml_path(base, name, kind)
            if not p.is_file():
                raise HTTPException(404, f"không có {kind} {name!r}")
            return {"name": name, "yaml": p.read_text(encoding="utf-8")}

        def put_source(name: str, body: dict, request: Request) -> dict:
            user, _ = _admin(request)
            from autoqa.audit import atomic_write

            p = _yaml_path(base, name, kind)
            if not p.is_file():
                raise HTTPException(404, f"không có {kind} {name!r}")
            source = str(body.get("yaml") or "")
            if name_check:
                name_check(source, name)
            tmp = p.with_suffix(".yaml.tmp-validate")
            atomic_write(tmp, source)
            try:
                validate(tmp)
            finally:
                tmp.unlink(missing_ok=True)
            if db_table and app.state.db.enabled:
                app.state.db.upsert(db_table, {"bot": bot, "name": name, "yaml": source}, "bot,name")
            atomic_write(p, source)
            return {"ok": True, "commit": _commit(user, f"sửa {kind} {name}", p)}

        def post_source(body: dict, request: Request) -> dict:
            user, _ = _admin(request)
            from autoqa.audit import atomic_write

            name = str(body.get("name") or "")
            p = _yaml_path(base, name, kind)
            if p.exists():
                raise HTTPException(400, f"đã có {kind} {name!r}")
            source = str(body.get("yaml") or "")
            if name_check:
                name_check(source, name)
            tmp = p.with_suffix(".yaml.tmp-validate")
            atomic_write(tmp, source)
            try:
                validate(tmp)
            finally:
                tmp.unlink(missing_ok=True)
            if db_table and app.state.db.enabled:
                app.state.db.upsert(db_table, {"bot": bot, "name": name, "yaml": source}, "bot,name")
            atomic_write(p, source)
            return {"ok": True, "commit": _commit(user, f"thêm {kind} {name}", p)}

        def delete_source(name: str, request: Request) -> dict:
            user, _ = _admin(request)
            p = _yaml_path(base, name, kind)
            if not p.is_file():
                raise HTTPException(404, f"không có {kind} {name!r}")
            if db_table and app.state.db.enabled:
                app.state.db.delete(db_table, {"bot": f"eq.{bot}", "name": f"eq.{name}"})
            p.unlink()
            return {"ok": True, "commit": _commit(user, f"xoá {kind} {name}", p)}
        return get_source, put_source, post_source, delete_source

    def _register_sources(bot: str) -> None:
        base_scn = _bot_dir(bots_dir, bot) / "scenarios"
        get_s, put_s, post_s, del_s = _source_crud(base_scn, "kịch bản", _validate_scenario_yaml, db_table="aq_scenarios", bot=bot)
        app.get(f"/api/bots/{bot}/scenarios/{{name}}/source")(get_s)
        app.put(f"/api/bots/{bot}/scenarios/{{name}}/source")(put_s)
        app.post(f"/api/bots/{bot}/scenarios")(post_s)
        app.delete(f"/api/bots/{bot}/scenarios/{{name}}")(del_s)

        base_sit = _bot_dir(bots_dir, bot) / "situations"

        def validate_situation(path: Path) -> None:
            from autoqa.scenario import _load_situation

            try:
                _load_situation(path)
            except ScenarioError as exc:
                raise HTTPException(400, f"YAML không hợp lệ: {exc}")

        def check_situation_name(source: str, name: str) -> None:
            data = yaml.safe_load(source) or {}
            got = str(data.get("name", "")) if isinstance(data, dict) else ""
            if got != name:
                raise HTTPException(400, f"name trong YAML phải là {name!r} (nhận {got!r}) — trùng tên file để mix tìm được")

        get_t, put_t, post_t, del_t = _source_crud(base_sit, "tình huống", validate_situation, check_situation_name, db_table="aq_situations", bot=bot)
        app.get(f"/api/bots/{bot}/situations/{{name}}/source")(get_t)
        app.put(f"/api/bots/{bot}/situations/{{name}}/source")(put_t)
        app.post(f"/api/bots/{bot}/situations")(post_t)
        app.delete(f"/api/bots/{bot}/situations/{{name}}")(del_t)

    # đăng ký route theo bot hiện có (bot mới thêm bằng git → khởi động lại app)
    if bots_dir.is_dir():
        for d in sorted(bots_dir.iterdir()):
            if d.is_dir() and (d / "profile.yaml").is_file():
                _register_sources(d.name)

    @app.get("/api/targets")
    def targets(request: Request) -> list[dict]:
        _auth(request)
        try:
            cfg = load_config(config_path)
        except (ConfigError, Exception) as exc:
            raise HTTPException(500, f"config lỗi: {exc}")
        return [{"name": t.name, "kind": t.kind} for t in cfg.values()]

    # ---------- chạy test (queue FIFO, 1 worker) ----------

    def _enqueue_run(app, *, bot, wanted, target_override, calls, concurrency, user) -> JobState:
        if not isinstance(wanted, list) or not wanted:
            raise HTTPException(400, "cần danh sách 'scenarios' (id kịch bản)")
        calls = max(1, min(int(calls or 1), MAX_CALLS_PER_RUN))
        concurrency = max(1, min(int(concurrency or 1), 4))
        suite = _load_bot_scenarios(bots_dir, bot)
        unknown = [w for w in wanted if w not in suite]
        if unknown:
            raise HTTPException(400, f"không có kịch bản: {', '.join(unknown)}")
        scenarios = [suite[w] for w in wanted]
        load_dotenv()
        try:
            t = load_config(config_path)
            llm = build_llm_caller(config_path, scenarios)
        except (LlmError, ConfigError) as exc:
            raise HTTPException(400, f"không dựng được run: {exc}")

        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id, seq = base, 0
        while run_id in app.state.jobs or (runs_dir / f"{run_id}.jsonl").exists():
            seq += 1
            run_id = f"{base}-{seq}"
        state = JobState(run_id=run_id, bot=bot, user=user, total=len(scenarios) * calls)
        app.state.jobs[run_id] = state
        app.state.pending.add(run_id)
        app.state.queue.put_nowait(
            QueueItem(
                state=state,
                scenarios=scenarios,
                targets=t,
                llm_caller=llm,
                target_override=target_override,
                concurrency=concurrency,
                calls=calls,
            )
        )
        return state

    @app.post("/api/runs")
    async def start_run(body: dict, request: Request) -> dict:
        name, _role = _auth(request)
        state = _enqueue_run(
            app,
            bot=str(body.get("bot") or ""),
            wanted=body.get("scenarios") or [],
            target_override=body.get("target") or None,
            calls=body.get("calls") or 1,
            concurrency=body.get("concurrency") or 1,
            user=name,
        )
        position = len(app.state.pending)
        return {
            "run_id": state.run_id,
            "total": state.total,
            "queue_position": position,
            "status_url": f"/api/runs/{state.run_id}/status",
        }

    @app.get("/api/runs/{run_id}/status")
    def run_status(run_id: str, request: Request) -> dict:
        _auth(request)
        state = app.state.jobs.get(run_id)
        if state is not None:
            done = len(_read_run_rows(runs_dir, run_id))
            pending = list(app.state.pending)
            return {
                "run_id": run_id,
                "status": state.status,
                "done": done if state.status in ("running", "queued") else state.total,
                "total": state.total,
                "queue_position": pending.index(run_id) + 1 if run_id in pending else 0,
                "error": state.error,
                "results": state.results,
            }
        if (runs_dir / f"{run_id}.jsonl").is_file():  # run từ lần chạy trước (sau restart)
            return {"run_id": run_id, "status": "done", "results": []}
        raise HTTPException(404, f"không có run {run_id}")

    # ---------- lịch sử, review, export ----------

    def _index_rows() -> list[dict]:
        if app.state.db.enabled:
            rows = app.state.db.maybe(app.state.db.call_rows_as_index)
            if rows is not None:
                return rows
        return list(reversed(_parse_index(runs_dir)))

    @app.get("/api/runs")
    def list_runs(request: Request) -> list[dict]:
        _auth(request)
        return _index_rows()

    @app.get("/api/runs/{run_id}/review")
    def get_review(run_id: str, request: Request) -> list[dict]:
        _auth(request)
        if app.state.db.enabled:
            rows = app.state.db.maybe(app.state.db.reviews, run_id)
            if rows is not None:
                return rows
        return _load_reviews(runs_dir, run_id)

    @app.post("/api/runs/{run_id}/review")
    def post_review(run_id: str, body: dict, request: Request) -> dict:
        name, _role = _auth(request)
        if not _RUN_ID_RE.match(run_id):
            raise HTTPException(400, "run_id không hợp lệ")
        if app.state.db.enabled:
            if not app.state.db.maybe(app.state.db.call_rows_as_jsonl, run_id):
                raise HTTPException(404, f"không có run {run_id}")
        elif not (runs_dir / f"{run_id}.jsonl").is_file():
            raise HTTPException(404, f"không có run {run_id}")
        verdict = str(body.get("verdict") or "")
        if verdict not in _VERDICTS:
            raise HTTPException(400, f"verdict phải một trong {_VERDICTS}")
        scenario = str(body.get("scenario") or "")
        call = str(body.get("call") or "1/1")
        anchor = body.get("anchor")
        if anchor is not None and not re.match(r"^T\d+$", str(anchor)):
            raise HTTPException(400, "anchor phải dạng T<số lượt>")
        entry = {
            "scenario": scenario,
            "call": call,
            "reviewer": name,
            "verdict": verdict,
            "anchor": str(anchor) if anchor else "",
            "note": str(body.get("note") or "")[:1000],
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        if app.state.db.enabled:
            app.state.db.save_review({**entry, "run_id": run_id})
        else:
            reviews = _load_reviews(runs_dir, run_id)
            reviews = [
                r
                for r in reviews
                if not (r.get("scenario") == scenario and r.get("call") == call and r.get("reviewer") == name)
            ]
            reviews.append(entry)
            _save_reviews(runs_dir, run_id, reviews)
        return entry

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str, request: Request) -> dict:
        _auth(request)
        if not _RUN_ID_RE.match(run_id):
            raise HTTPException(400, "run_id không hợp lệ")
        if app.state.db.enabled:
            rows = app.state.db.maybe(app.state.db.call_rows_as_jsonl, run_id) or []
        else:
            rows = _read_run_rows(runs_dir, run_id)
        if not rows:
            raise HTTPException(404, f"không có run {run_id}")
        reviews = get_review(run_id, request)
        return {
            "run_id": run_id,
            "report_exists": (runs_dir / f"{run_id}.md").is_file(),
            "scenarios": rows,
            "reviews": reviews,
        }

    @app.get("/api/runs/{run_id}/export")
    def export_run(run_id: str, request: Request, format: str = "md") -> PlainTextResponse:
        _auth(request)
        rows = _read_run_rows(runs_dir, run_id)
        if not rows:
            raise HTTPException(404, f"không có run {run_id}")
        reviews = _load_reviews(runs_dir, run_id)
        if format == "csv":
            lines = ["run,scenario,call,status,conversation,verdict,reviewer,anchor,note"]
            for r in rows:
                rv = next(
                    (v for v in reviews if v.get("scenario") == f"{r['suite']}/{r['scenario']}" and v.get("call") == r.get("call", "1/1")),
                    {},
                )
                note = str(rv.get("note", "")).replace('"', '""')
                lines.append(
                    f"{run_id},{r['suite']}/{r['scenario']},{r.get('call', '1/1')},{r['status']},"
                    f"{r.get('conversation_id') or ''},{rv.get('verdict', '')},{rv.get('reviewer', '')},"
                    f"{rv.get('anchor', '')},\"{note}\""
                )
            return PlainTextResponse("\n".join(lines), media_type="text/csv")
        # markdown
        lines = [f"# Run {run_id}", ""]
        for r in rows:
            scn = f"{r['suite']}/{r['scenario']}"
            rv = next((v for v in reviews if v.get("scenario") == scn and v.get("call") == r.get("call", "1/1")), {})
            verdict = f" — review: **{rv['verdict']}** bởi {rv['reviewer']}" if rv else " — chưa review"
            lines.append(f"## {scn} ({r.get('call', '1/1')}) — {r['status']}{verdict}")
            lines.append(f"Conv: `{r.get('conversation_id') or '—'}`")
            if rv.get("anchor"):
                lines.append(f"Neo: {rv['anchor']}")
            if rv.get("note"):
                lines.append(f"Ghi chú: {rv['note']}")
            lines.append("")
        return PlainTextResponse("\n".join(lines), media_type="text/markdown")

    # ---------- thống kê (dashboard) ----------

    @app.get("/api/stats")
    def stats(request: Request, bot: str = "", days: int = 14) -> dict:
        _auth(request)
        days = max(1, min(int(days or 14), 90))
        since = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        rows = [r for r in _index_rows() if r["run"][:8] >= since]
        if bot:
            rows = [r for r in rows if r["scenario"].split("/")[0] == bot or r["target"] == bot]

        def _reviews_of(run_id: str) -> dict:
            src = (
                app.state.db.reviews(run_id)
                if app.state.db.enabled
                else _load_reviews(runs_dir, run_id)
            )
            return {(v.get("scenario"), v.get("call")): v for v in src}

        run_ids = sorted({r["run"] for r in rows})
        review_maps = {rid: _reviews_of(rid) for rid in run_ids}
        per_scn: dict[str, dict] = {}
        for r in rows:
            scn = r["scenario"]
            call = ""
            m = re.match(r"^(.*) \((\d+/\d+)\)$", scn)
            if m:
                scn, call = m.group(1), m.group(2)
            d = per_scn.setdefault(
                scn, {"scenario": scn, "target": r["target"], "total": 0, "pass": 0, "fail": 0, "blocked": 0, "reviewed": 0, "issues": 0}
            )
            d["total"] += 1
            status = r["status"].lower()  # pass | fail | blocked
            d[status] = d.get(status, 0) + 1
            rv = review_maps.get(r["run"], {}).get((scn, call or "1/1"))
            if rv:
                d["reviewed"] += 1
                d["issues"] += rv.get("verdict") == "issue"
        out = {
            "days": days,
            "bot": bot or None,
            "runs": len(run_ids),
            "rows": len(rows),
            "reviewed": sum(d["reviewed"] for d in per_scn.values()),
            "scenarios": sorted(
                per_scn.values(),
                key=lambda d: (-(d["fail"] + d["blocked"] + d["issues"]), d["scenario"]),
            ),
        }
        return out

    # ---------- static ----------

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    return app
