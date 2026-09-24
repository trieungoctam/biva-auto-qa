"""Lớp L1 — protocol, deterministic, không cần LLM.

Chấm hợp đồng thoại quan sát được từ transcript:
- reply_nonempty: bot phải trả lời chữ khi kịch bản yêu cầu;
- tag: tag cuối lượt đúng kỳ vọng (chỉ kiểm khi kịch bản khai báo);
- forbidden_phrase: cụm cấm không xuất hiện trong lời bot (không phân biệt hoa thường);
- call_ended_early: bot |ENDCALL khi kịch bản còn lượt khách chưa nói.
"""

from __future__ import annotations

from autoqa.adapter import AssistantReply
from autoqa.oracle import Check, FAIL, PASS
from autoqa.scenario import Scenario, Turn


def check_turn(index: int, turn: Turn, reply: AssistantReply) -> list[Check]:
    checks: list[Check] = []
    spoken, tag = reply.spoken, reply.normalized_tag
    if turn.expect.reply_nonempty:
        if spoken:
            checks.append(Check("reply_nonempty", PASS))
        else:
            checks.append(Check("reply_nonempty", FAIL, f"turn {index}: bot trả lời rỗng"))


    if turn.expect.tag is not None:
        want = turn.expect.tag
        got = tag or "không có tag"
        checks.append(
            Check("tag", PASS if tag == want else FAIL, f"turn {index}: kỳ vọng |{want}, nhận {got}")
        )
    return checks


def check_forbidden_phrases(scenario: Scenario, transcript: list[dict]) -> list[Check]:
    checks: list[Check] = []
    for phrase in scenario.forbidden_phrases:
        needle = phrase.lower()
        for row in transcript:
            if needle in row["assistant"].lower():
                checks.append(
                    Check(
                        "forbidden_phrase",
                        FAIL,
                        f"turn {row['turn']}: lời bot chứa cụm cấm {phrase!r}",
                    )
                )
    return checks
