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

    ui = sub.add_parser("ui", help="mở web UI (chạy test, xem transcript, tra conv ID)")
    ui.add_argument("--bots-dir", default="bots", help="thư mục bots/ (mỗi bot một thư mục)")
    ui.add_argument("--runs-dir", default="runs", help="thư mục runs/")
    ui.add_argument("--config", default="config.yaml", help="file config (target whitelist + llm)")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8788)
    return parser


def _append_index(out_dir: Path, run_id: str, results, report_path: Path) -> Path:
    """Ghi nối chỉ mục runs/INDEX.md — mỗi kịch bản một dòng, để tra conversation_id về sau."""
    index = out_dir / "INDEX.md"
    header = "| Run | Target | Kịch bản | Trạng thái | Conversation | Báo cáo |"
    sep = "|---|---|---|---|---|---|"
    lines = [
        f"| {run_id} | {r.target_name or '?'} | `{r.id}` | {r.status} | "
        f"{r.conversation_id or '—'} | {report_path} |"
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
        )
    )
    write_report(results, report_path, run_id=run_id)
    index_path = _append_index(out_dir, run_id, results, report_path)

    for r in results:
        conv = f"  [conv {r.conversation_id}]" if r.conversation_id else ""
        marker = {"PASS": "ok ", "FAIL": "FAIL", "BLOCKED": "BLOCK"}.get(r.status, "?")
        print(f"{marker} {r.status:7s} {r.target_name:12s} {r.id}{conv}")
    print(f"\nJSONL:   {jsonl_path}")
    print(f"Báo cáo: {report_path}")
    print(f"Chỉ mục: {index_path}")
    return 0 if all(r.status == "PASS" for r in results) else 1


def _ui_main(args) -> int:
    try:
        import uvicorn

        from autoqa.webui import create_app
    except ImportError as exc:
        print(f"Thiếu extras UI: pip install -e '.[ui]' ({exc})")
        return 2
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
    return _run_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
