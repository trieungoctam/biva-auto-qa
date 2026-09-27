"""CLI: chạy suite kịch bản QA cho một hoặc nhiều callbot.

    python -m autoqa run --suite 'bots/live-demo/scenarios/*.yaml' --concurrency 2

Chấm tự động chỉ ở lớp protocol (deterministic). LLM duy nhất một vai: caller
đóng vai khách sinh lời thoại cho kịch bản mode llm. Chất lượng nghiệp vụ của
lời bot do người review trực tiếp trên transcript (JSONL + báo cáo markdown).

Exit code: 0 khi mọi kịch bản PASS; 1 khi có FAIL/BLOCKED; 2 khi cấu hình lỗi.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path
import yaml

from autoqa.config import load_config
from autoqa.llm import LlmClient, LlmError, build_llm_caller, load_dotenv
from autoqa.report import write_report
from autoqa.runner import run_suite
from autoqa.scenario import load_suite


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autoqa", description="Bot QA cho callbot BIVA")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="chạy một suite kịch bản")
    run.add_argument("--suite", required=True, help="glob tới file YAML kịch bản")
    run.add_argument("--config", default="config.yaml", help="file khai báo target whitelist + llm")
    run.add_argument("--target", help="đè target của mọi kịch bản (tên trong config)")
    run.add_argument(
        "--bot-id",
        type=str,
        help="đè bot_id gửi vào init/chat — CHỈ dùng kèm --target (nhiều bot sẽ ambiguous)",
    )
    run.add_argument("--concurrency", type=int, default=1, help="số kịch bản chạy song song")
    run.add_argument("--out", default="runs", help="thư mục xuất JSONL + báo cáo")
    run.add_argument("--calls", type=int, default=1, help="số conversation mỗi kịch bản (bắt lỗi lúc được lúc không)")
    run.add_argument("--user", default="cli", help="tên người chạy ghi vào INDEX (vd. tên bạn khi chạy tay)")

    dbm = sub.add_parser("db-migrate", help="đẩy dữ liệu file (bots, runs, reviews, users) lên Supabase")
    dbm.add_argument("--bots-dir", default="bots")
    dbm.add_argument("--runs-dir", default="runs")
    dbm.add_argument("--users-file", default="users.yaml")
    dbm.add_argument("--config", default="config.yaml")

    ui = sub.add_parser("ui", help="mở web UI (chạy test, xem transcript, tra conv ID)")
    ui.add_argument("--bots-dir", default="bots", help="thư mục bots/ (mỗi bot một thư mục)")
    ui.add_argument("--runs-dir", default="runs", help="thư mục runs/")
    ui.add_argument("--config", default="config.yaml", help="file config (target whitelist + llm)")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8788)
    return parser


def _append_index(out_dir: Path, run_id: str, results, report_path: Path, user: str = "cli") -> Path:
    """Ghi nối chỉ mục runs/INDEX.md — mỗi call một dòng, để tra conversation_id về sau."""
    index = out_dir / "INDEX.md"
    header = "| Run | Target | Kịch bản | Trạng thái | Conversation | Người chạy | Báo cáo |"
    sep = "|---|---|---|---|---|---|---|"
    lines = [
        f"| {run_id} | {r.target_name or '?'} | `{r.id}`"
        + (f" ({r.call_index}/{r.calls})" if r.calls > 1 else "")
        + f" | {r.status} | {r.conversation_id or '—'} | {user} | {report_path} |"
        for r in results
    ]
    exists = index.exists()
    with index.open("a", encoding="utf-8") as f:
        if not exists:
            f.write(header + "\n" + sep + "\n")
        f.write("\n".join(lines) + "\n")
    return index


def _run_main(args) -> int:
    if args.bot_id is not None and not args.target:
        print("Lỗi: --bot-id chỉ dùng kèm --target (chạy nhiều bot thì mỗi target đã có bot_id riêng).")
        return 2

    load_dotenv()
    targets = load_config(args.config)
    scenarios = load_suite(args.suite)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out)
    jsonl_path = out_dir / f"{run_id}.jsonl"
    report_path = out_dir / f"{run_id}.md"

    llm_caller: LlmClient | None = None
    if any(s.mode == "llm" for s in scenarios):
        try:
            llm_caller = build_llm_caller(args.config, scenarios)
        except LlmError as exc:
            print(f"Lỗi: {exc}")
            return 2
    results = asyncio.run(
        run_suite(
            targets,
            scenarios,
            run_id=run_id,
            target_override=args.target,
            bot_id=args.bot_id,
            out_jsonl=jsonl_path,
            llm_caller=llm_caller,
            concurrency=args.concurrency,
            calls=args.calls,
        )
    )
    write_report(results, report_path, run_id=run_id)
    index_path = _append_index(out_dir, run_id, results, report_path, user=args.user)
    from autoqa.db import Db

    db = Db()
    if db.enabled:
        db.maybe(db.push_run, run_id, [r.to_row(run_id) for r in results], bot=scenarios[0].suite if scenarios else "", user=args.user)

    for r in results:
        conv = f"  [conv {r.conversation_id}]" if r.conversation_id else ""
        call = f" (call {r.call_index}/{r.calls})" if r.calls > 1 else ""
        marker = {"PASS": "ok ", "FAIL": "FAIL", "BLOCKED": "BLOCK"}.get(r.status, "?")
        print(f"{marker} {r.status:7s} {r.target_name:12s} {r.id}{call}{conv}")
    print(f"\nJSONL:   {jsonl_path}")
    print(f"Báo cáo: {report_path}")
    print(f"Chỉ mục: {index_path}")
    return 0 if all(r.status == "PASS" for r in results) else 1


def _db_migrate_main(args) -> int:
    from autoqa.db import Db

    load_dotenv()
    db = Db()
    if not db.enabled:
        print("Lỗi: đặt SUPABASE_URL + SUPABASE_SERVICE_KEY trong .env trước khi migrate.")
        return 2

    import json as _json
    from autoqa.users import UserStore

    bots_dir, runs_dir = Path(args.bots_dir), Path(args.runs_dir)
    n_bots = n_scn = n_sit = n_runs = n_calls = n_rev = n_users = 0
    for d in sorted(bots_dir.iterdir()) if bots_dir.is_dir() else []:
        if not d.is_dir() or not (d / "profile.yaml").is_file():
            continue
        prof = yaml.safe_load((d / "profile.yaml").read_text(encoding="utf-8")) or {}
        bfile = d / "knowledge" / "business.md"
        db.upsert(
            "aq_bots",
            {
                "bot": d.name,
                "display_name": str(prof.get("display_name") or d.name),
                "target": str(prof.get("target") or ""),
                "business": bfile.read_text(encoding="utf-8") if bfile.is_file() else "",
            },
            "bot",
        )
        n_bots += 1
        for table, folder in (("aq_scenarios", "scenarios"), ("aq_situations", "situations")):
            fdir = d / folder
            for f in sorted(fdir.glob("*.yaml")) if fdir.is_dir() else []:
                db.upsert(table, {"bot": d.name, "name": f.stem, "yaml": f.read_text(encoding="utf-8")}, "bot,name")
                n_scn += table == "aq_scenarios"
                n_sit += table == "aq_situations"

    users_file = Path(args.users_file)
    if users_file.is_file():
        raw = yaml.safe_load(users_file.read_text(encoding="utf-8")) or []
        for u in raw if isinstance(raw, list) else []:
            db.upsert("aq_users", {"name": u["name"], "key_hash": u["key_hash"], "role": u.get("role", "member")}, "name")
            n_users += 1

    for f in sorted(runs_dir.glob("*.jsonl")) if runs_dir.is_dir() else []:
        rows = [_json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
        if not rows:
            continue
        run_id = f.stem
        user = rows[0].get("user") or "cli"
        db.push_run(run_id, rows, bot=rows[0].get("suite") or "", user=user)
        n_runs += 1
        n_calls += len(rows)
        rv = runs_dir / f"{run_id}.review.yaml"
        if rv.is_file():
            for entry in yaml.safe_load(rv.read_text(encoding="utf-8")) or []:
                if not isinstance(entry, dict) or not all(entry.get(k) for k in ("scenario", "reviewer", "verdict")):
                    continue  # file review định dạng cũ của luồng judge đã xoá
                db.save_review(
                    {
                        "run_id": run_id,
                        "scenario": entry["scenario"],
                        "call": str(entry.get("call") or "1/1"),
                        "reviewer": entry["reviewer"],
                        "verdict": entry["verdict"] if entry["verdict"] in ("ok", "issue", "warn") else "warn",
                        "anchor": str(entry.get("anchor") or ""),
                        "note": str(entry.get("note") or "")[:1000],
                    }
                )
                n_rev += 1

    print(f"Đã đẩy lên Supabase: {n_bots} bot · {n_scn} kịch bản · {n_sit} tình huống · "
          f"{n_runs} run ({n_calls} call) · {n_rev} review")
    return 0


def _ui_main(args) -> int:
    try:
        import uvicorn

        from autoqa.webui import create_app
    except ImportError as exc:
        print(f"Thiếu extras UI: pip install -e '.[ui]' ({exc})")
        return 2
    load_dotenv()
    uvicorn.run(
        create_app(bots_dir=args.bots_dir, runs_dir=args.runs_dir, config_path=args.config),
        host=args.host,
        port=args.port,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "ui":
        return _ui_main(args)
    if args.command == "db-migrate":
        return _db_migrate_main(args)
    return _run_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
