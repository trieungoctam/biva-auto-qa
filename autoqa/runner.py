"""Chạy kịch bản theo target whitelist; ghi JSONL crash-safe (fsync mỗi dòng).

Hai mode:
- script: turns cố định, chấm deterministic (protocol).
- llm: goal-driven — Caller LLM đóng vai khách, sinh lời thoại từng lượt theo
  goal/persona (mẫu văn phong từ call_scripts thật).

Chất lượng NGHIỆP VỤ của lời bot không chấm bằng LLM: transcript đầy đủ nằm
trong JSONL + báo cáo markdown, người review đọc và tự kết luận.

Nhiều bot × nhiều kịch bản: mỗi kịch bản tự khai target; chạy song song theo
`concurrency` (mỗi kịch bản một phiên chat riêng, kết quả ghi JSONL theo thứ tự
hoàn tất, mỗi dòng fsync ngay).

Lỗi hạ tầng (mạng/timeout/LLM) → BLOCKED, không phán xét bot. Lỗi assertion → FAIL.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from autoqa import caller
from autoqa.adapter import open_session
from autoqa.config import ConfigError, Target, resolve_target
from autoqa.llm import ChatJsonModel, LlmClient, LlmError
from autoqa.oracle import BLOCKED, Check, FAIL, PASS, worst
from autoqa.oracle.protocol import check_forbidden_phrases, check_turn
from autoqa.scenario import Expect, Scenario, Turn


@dataclass
class ScenarioResult:
    scenario: Scenario
    status: str
    target_name: str = ""
    conversation_id: str = ""
    checks: list[Check] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def id(self) -> str:
        return self.scenario.id

    def first_failure(self) -> Check | None:
        return next((c for c in self.checks if c.status == FAIL), None)

    def to_row(self, run_id: str) -> dict:
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "suite": self.scenario.suite,
            "scenario": self.scenario.name,
            "conversation_id": self.conversation_id,
            "target": self.target_name,
            "checks": [c.to_dict() for c in self.checks],
            "status": self.status,
            "error": self.error,
            "transcript": self.transcript,
        }


async def run_script_scenario(
    target: Target, scenario: Scenario, *, transport=None
) -> ScenarioResult:
    session = open_session(target, scenario, transport=transport)
    result = ScenarioResult(
        scenario=scenario,
        status=PASS,
        target_name=target.name,
        conversation_id=getattr(session, "conversation_id", ""),
    )
    try:
        await session.start()
        for i, turn in enumerate(scenario.turns):
            reply = await session.send(turn.say)
            result.transcript.append(
                {"turn": i, "user": turn.say, "assistant": reply.text, "tag": reply.normalized_tag}
            )
            result.checks.extend(check_turn(i, turn, reply))
            remaining = len(scenario.turns) - i - 1
            if reply.normalized_tag == "ENDCALL" and remaining:
                result.checks.append(
                    Check(
                        "call_ended_early",
                        FAIL,
                        f"turn {i}: bot |ENDCALL khi kịch bản còn {remaining} lượt khách",
                    )
                )
                break
    except httpx.HTTPError as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.status = BLOCKED
        return result
    finally:
        await session.aclose()

    result.checks.extend(check_forbidden_phrases(scenario, result.transcript))
    result.status = worst([c.status for c in result.checks])
    return result


async def run_goal_scenario(
    target: Target,
    scenario: Scenario,
    llm_caller: "ChatJsonModel",
) -> ScenarioResult:
    if scenario.mode != "llm" or scenario.max_turns is None:
        raise ValueError(f"{scenario.id}: run_goal_scenario chỉ chạy cho kịch bản mode llm hợp lệ")
    session = open_session(target, scenario)
    result = ScenarioResult(
        scenario=scenario,
        status=PASS,
        target_name=target.name,
        conversation_id=getattr(session, "conversation_id", ""),
    )
    caller_done = False
    try:
        await session.start()
        while len(result.transcript) < scenario.max_turns:
            action = await caller.next_turn(llm_caller, scenario, result.transcript)
            if action["done"]:
                result.checks.append(
                    Check("goal_completed", PASS, action["note"] or "caller báo hoàn tất mục tiêu")
                )
                caller_done = True
                break
            say = action["say"]
            reply = await session.send(say)
            turn_index = len(result.transcript)
            result.transcript.append(
                {
                    "turn": turn_index,
                    "user": say,
                    "assistant": reply.text,
                    "tag": reply.normalized_tag,
                    "caller_note": action["note"],
                }
            )

            expect = Expect(tag=None, reply_nonempty=say.strip() not in ("", "<silence>"))
            result.checks.extend(check_turn(turn_index, Turn(say=say, expect=expect), reply))
            if reply.normalized_tag == "ENDCALL":
                result.checks.append(
                    Check(
                        "call_ended_early",
                        FAIL,
                        f"turn {turn_index}: bot |ENDCALL trước khi khách hoàn tất mục tiêu",
                    )
                )
                break
        if not caller_done and len(result.transcript) >= scenario.max_turns:
            result.checks.append(
                Check("goal_not_completed", FAIL, f"hết {scenario.max_turns} lượt mà chưa đạt mục tiêu")
            )
    except (LlmError, httpx.HTTPError) as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.status = BLOCKED
        return result
    finally:
        await session.aclose()
    result.checks.extend(check_forbidden_phrases(scenario, result.transcript))
    result.status = worst([c.status for c in result.checks])
    return result


async def run_scenario(
    target: Target,
    scenario: Scenario,
    *,
    llm_caller: LlmClient | None = None,
    transport=None,
) -> ScenarioResult:
    if scenario.mode == "llm":
        if llm_caller is None:
            raise ConfigError(
                f"{scenario.id}: mode llm cần LLM — khai báo mục 'llm' (hoặc llm_caller) trong config.yaml"
            )
        return await run_goal_scenario(target, scenario, llm_caller)
    return await run_script_scenario(target, scenario, transport=transport)


async def run_suite(
    targets: dict[str, Target],
    scenarios: list[Scenario],
    *,
    run_id: str,
    target_override: str | None = None,
    bot_id: int | None = None,
    out_jsonl: Path | None = None,
    llm_caller: LlmClient | None = None,
    transport_factory=None,
    concurrency: int = 1,
) -> list[ScenarioResult]:
    """Chạy (song song theo `concurrency`) từng kịch bản vào target của nó.

    Mỗi kịch bản một phiên chat riêng; dòng JSONL ghi ngay khi kịch bản xong
    (fsync dưới lock) — crash giữa chừng không mất kịch bản đã chạy.
    Kết quả trả về theo thứ tự khai báo ban đầu.
    """
    if any(s.mode == "llm" for s in scenarios) and llm_caller is None:
        raise ConfigError(
            "suite có kịch bản mode llm nhưng chưa có LLM caller "
            "(khai báo mục 'llm' hoặc 'llm_caller' trong config.yaml)"
        )

    semaphore = asyncio.Semaphore(max(1, concurrency))
    write_lock = asyncio.Lock()
    out = None
    if out_jsonl is not None:
        out_jsonl = Path(out_jsonl)
        out_jsonl.parent.mkdir(parents=True, exist_ok=True)
        out = out_jsonl.open("a", encoding="utf-8")

    async def _run_one(scenario: Scenario) -> ScenarioResult:
        async with semaphore:
            target = resolve_target(targets, target_override or scenario.target)
            if bot_id is not None:
                target = target.with_overrides(bot_id)
            transport = transport_factory() if transport_factory else None
            result = await run_scenario(
                target, scenario, llm_caller=llm_caller, transport=transport
            )
            if out is not None:
                async with write_lock:
                    out.write(json.dumps(result.to_row(run_id), ensure_ascii=False) + "\n")
                    out.flush()
                    os.fsync(out.fileno())
            return result

    clients = {id(llm_caller)} if llm_caller is not None else set()
    try:
        results = await asyncio.gather(*(_run_one(s) for s in scenarios))
        return list(results)
    finally:
        if out is not None:
            out.close()
        if llm_caller is not None and id(llm_caller) in clients:
            await llm_caller.aclose()
