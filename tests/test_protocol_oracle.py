from pathlib import Path

from autoqa.adapter import AssistantReply
from autoqa.oracle import FAIL, PASS
from autoqa.oracle.protocol import check_forbidden_phrases, check_turn
from autoqa.scenario import Expect, Scenario, Turn

def _turn(tag: str | None = None, nonempty: bool = True) -> Turn:
    return Turn(say="alô", expect=Expect(tag=tag, reply_nonempty=nonempty))


def test_empty_reply_fails_nonempty_check():
    checks = check_turn(0, _turn(), AssistantReply("", None))
    assert (checks[0].name, checks[0].status) == ("reply_nonempty", FAIL)


def test_silence_turn_allows_empty_reply():
    checks = check_turn(0, _turn(nonempty=False), AssistantReply("", None))
    assert all(c.status == PASS for c in checks)


def test_tag_match_passes_and_mismatch_fails():
    ok = check_turn(0, _turn(tag="CHAT"), AssistantReply("Dạ bên em có chuyến 23:30.|CHAT", "CHAT"))
    bad = check_turn(0, _turn(tag="CHAT"), AssistantReply("Dạ.|ENDCALL", "ENDCALL"))
    assert ok[-1].status == PASS
    assert bad[-1].status == FAIL and "|CHAT" in bad[-1].detail


def test_missing_tag_reported_when_expected():
    checks = check_turn(0, _turn(tag="ENDCALL"), AssistantReply("Cảm ơn anh.", None))
    assert checks[-1].status == FAIL
    assert "không có tag" in checks[-1].detail


def test_forbidden_phrase_case_insensitive():
    scenario = Scenario(
        path=Path("x"), suite="s", name="n", target="mock", forbidden_phrases=("MÁY BAY",)
    )
    transcript = [{"turn": 1, "user": "a", "assistant": "Anh đi máy bay hay xe ạ?", "tag": "CHAT"}]
    checks = check_forbidden_phrases(scenario, transcript)
    assert len(checks) == 1
    assert checks[0].status == FAIL and "turn 1" in checks[0].detail
