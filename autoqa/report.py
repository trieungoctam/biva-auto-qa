"""Báo cáo markdown theo nhóm target (bot).

Chấm tự động chỉ ở lớp protocol (deterministic). Chất lượng NGHIỆP VỤ của lời
bot do người review trực tiếp trên transcript — báo cáo in kèm transcript đầy đủ
của mọi kịch bản có vấn đề.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from autoqa.oracle import BLOCKED, FAIL
from autoqa.runner import ScenarioResult

_LEGEND = {
    "PASS": "đúng hợp đồng thoại quan sát được",
    "FAIL": "vi phạm deterministic (tag/rỗng/cụm cấm/ENDCALL sớm)",
    BLOCKED: "lỗi hạ tầng (mạng/timeout/HTTP/LLM) — chưa kết luận được bot",
}


def _detail(r: ScenarioResult) -> str:
    if r.status == BLOCKED and r.error:
        return f"`{r.error}`"
    fail = r.first_failure()
    if fail:
        return f"{fail.name}: {fail.detail}"
    return "—"


def write_report(results: list[ScenarioResult], out_path: Path, *, run_id: str) -> Path:
    by_target: dict[str, list[ScenarioResult]] = defaultdict(list)
    for r in results:
        by_target[r.target_name or "?"].append(r)
    # gom nhóm theo kịch bản khi chạy nhiều calls: hiển thị "PASS 3/5"
    by_scenario: dict[tuple[str, str], list[ScenarioResult]] = defaultdict(list)
    for r in results:
        by_scenario[(r.target_name or "?", r.id)].append(r)

    lines: list[str] = [
        f"# Báo cáo auto-qa — run `{run_id}`",
        "",
        f"- Số kịch bản: {len(by_scenario)} trên {len(by_target)} target"
        + (f" · {len(results)} calls" if len(results) > len(by_scenario) else ""),
    ]
    for target_name in sorted(by_target):
        counts = Counter(r.status for r in by_target[target_name])
        summary = ", ".join(f"{s}: {counts.get(s, 0)}" for s in (FAIL, BLOCKED, "PASS"))
        n_scn = sum(1 for t, _ in by_scenario if t == target_name)
        lines.append(f"- **{target_name}** ({n_scn} kịch bản): {summary}")

    lines += ["", "## Kết quả chi tiết", "", "| Target | ID | Kết quả | Chi tiết |", "|---|---|---|---|"]
    for (target_name, scn_id), rs in sorted(by_scenario.items()):
        if len(rs) == 1:
            lines.append(f"| {target_name} | `{scn_id}` | **{rs[0].status}** | {_detail(rs[0])} |")
            continue
        n_pass = sum(1 for r in rs if r.status == "PASS")
        group = "PASS" if n_pass == len(rs) else ("BLOCKED" if all(r.status == "BLOCKED" for r in rs) else FAIL)
        bad = next((r for r in rs if r.status != "PASS"), rs[0])
        lines.append(f"| {target_name} | `{scn_id}` | **{group} {n_pass}/{len(rs)}** | {_detail(bad)} |")

    lines += ["", "## Quy ước kết quả"]
    lines += [f"- **{k}**: {v}" for k, v in _LEGEND.items()]

    problem = [r for r in results if r.status in (FAIL, BLOCKED)]
    if problem:
        lines += ["", "## Chi tiết các kịch bản cần xem"]
        for r in problem:
            call = f" (call {r.call_index}/{r.calls})" if r.calls > 1 else ""
            lines.append(f"### `{r.id}`{call} ({r.target_name}) — {r.status}")
            lines.append(f"Conv: `{r.conversation_id}`")
            if r.error:
                lines += [f"- Lỗi: `{r.error}`"]
            for c in r.checks:
                if c.status != "PASS":
                    lines.append(f"- **{c.status}** `{c.name}`: {c.detail}")
            lines += ["", "Transcript:"]
            for row in r.transcript:
                tag = f" `|{row['tag']}`" if row.get("tag") else ""
                lines.append(f"- T{row['turn']} khách: {row['user'] or '(im lặng)'}")
                lines.append(f"  bot: {row['assistant'] or '(rỗng)'}{tag}")
            lines.append("")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path
