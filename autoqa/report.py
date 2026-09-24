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

    lines: list[str] = [
        f"# Báo cáo auto-qa — run `{run_id}`",
        "",
        f"- Số kịch bản: {len(results)} trên {len(by_target)} target",
    ]
    for target_name in sorted(by_target):
        counts = Counter(r.status for r in by_target[target_name])
        summary = ", ".join(f"{s}: {counts.get(s, 0)}" for s in (FAIL, BLOCKED, "PASS"))
        lines.append(f"- **{target_name}** ({len(by_target[target_name])} kịch bản): {summary}")

    lines += ["", "## Kết quả chi tiết", "", "| Target | ID | Kết quả | Chi tiết |", "|---|---|---|---|"]
    for target_name in sorted(by_target):
        for r in by_target[target_name]:
            lines.append(f"| {target_name} | `{r.id}` | **{r.status}** | {_detail(r)} |")

    lines += ["", "## Quy ước kết quả"]
    lines += [f"- **{k}**: {v}" for k, v in _LEGEND.items()]

    problem = [r for r in results if r.status in (FAIL, BLOCKED)]
    if problem:
        lines += ["", "## Chi tiết các kịch bản cần xem"]
        for r in problem:
            lines += [f"### `{r.id}` ({r.target_name}) — {r.status}", f"Conv: `{r.conversation_id}`"]
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
