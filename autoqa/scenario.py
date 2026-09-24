"""Kịch bản QA là dữ liệu (YAML), không phải code.

Hai mode:
1. script — turns cố định, chấm deterministic:
    suite: examples
    target: mock
    turns: [{say: "...", expect: {tag: CHAT}}]

2. llm — goal-driven, LLM (caller) đóng vai khách sinh lời thoại; mix được nhiều tình huống:
    mode: llm
    profile: live-demo          # TÙY CHỌN — mặc định tự kế thừa profile.yaml của bot
    target: live-demo           # có thể bỏ nếu profile đã khai
    persona: {name, phone, style}
    goal: "mục tiêu cuộc gọi"
    max_turns: 8                # có thể bỏ nếu profile defaults khai
    context: |                  # luật RIÊNG của kịch bản (cộng vào nghiệp vụ nền)
      - ...
    call_scripts: []            # transcript mẫu văn phong (file/thư mục/inline)
    mix: [tre-em, doi-y]        # ghép tình huống trong bots/<bot>/situations/

MỖI BOT MỘT THƯ MỤC — bots/<bot>/:
    raw/                  # tài liệu GỐC — chỉ ở local, gitignore, KHÔNG push, code không đọc
    knowledge/            # sản phẩm ĐÃ XỬ LÝ từ raw — nguồn trust duy nhất, push được lên cloud
      business.md         #   nghiệp vụ nền bot
      call-scripts/*.txt  #   mẫu văn phong (đã ẩn danh)
    situations/*.yaml     # tình huống tái sử dụng: goal/context/persona/forbidden/extra_turns
    profile.yaml          # hồ sơ bot: bot/target/display_name + business_file + call_scripts
    scenarios/*.yaml      # kịch bản đã define sẵn

TÌNH HUỐNG (situations/<tên>.yaml) — mảnh nghiệp vụ dùng lại, không phải kịch bản:
    name: tre-em          # bắt buộc
    goal: |               # tùy chọn — nối vào goal kịch bản khi được mix
    context: |            # tùy chọn — luật riêng của tình huống
    persona: {...}        # tùy chọn — gộp vào persona (tình huống thắng key trùng)
    forbidden_phrases: [] # tùy chọn — hợp vào danh sách cấm
    extra_turns: 3        # tùy chọn — cộng vào max_turns khi mix
    call_scripts: []      # tùy chọn

`mix: [a, b]` = một cuộc gọi chứa nhiều tình huống đan nhau: goal nối thêm mục
tiêu, context nối luật, forbidden_phrases hợp lại (không trùng), max_turns cộng
extra_turns. Chỉ dùng cho mode llm. Kịch bản nằm dưới profile.yaml tự kế thừa
nghiệp vụ nền; khai `profile: <bot>` tường minh thì tên phải khớp `bot:`.
Nghiệp vụ nền đọc từ `business_file` (khuyến nghị — sống trong knowledge/),
hoặc inline `business` cho bot nhỏ. Hai mục này loại trừ nhau.

Nghiệp vụ EFFECTIVE = business (profile/knowledge) + context (kịch bản + tình
huống mix). Kịch bản thắng profile ở mọi trường nó khai tường minh (target,
max_turns, persona key).
"""

from __future__ import annotations

import glob as _glob
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

VALID_TAGS = ("CHAT", "ENDCALL")
VALID_MODES = ("script", "llm")


class ScenarioError(Exception):
    """Kịch bản (hoặc profile) không hợp lệ."""


@dataclass(frozen=True)
class Expect:
    tag: str | None = None
    reply_nonempty: bool = True


@dataclass(frozen=True)
class Turn:
    say: str
    expect: Expect = field(default_factory=Expect)


@dataclass(frozen=True)
class Scenario:
    path: Path
    suite: str
    name: str
    target: str
    mode: str = "script"
    profile: str | None = None           # tên bot (bots/<bot>/profile.yaml)
    business: str = ""                   # nghiệp vụ nền từ profile
    persona: dict[str, Any] = field(default_factory=dict)
    turns: tuple[Turn, ...] = ()          # mode script
    forbidden_phrases: tuple[str, ...] = ()
    goal: str | None = None               # mode llm
    max_turns: int | None = None          # mode llm
    context: str = ""                     # mode llm: luật RIÊNG của kịch bản
    call_scripts: tuple[str, ...] = ()    # mode llm: transcript mẫu đã đọc nội dung
    mix: tuple[str, ...] = ()             # mode llm: tên tình huống trong bots/<bot>/situations/

    @property
    def id(self) -> str:
        return f"{self.suite}/{self.name}"

    @property
    def effective_context(self) -> str:
        """Nghiệp vụ EFFECTIVE cho caller: nghiệp vụ bot (profile) + luật riêng."""
        parts = [p for p in (self.business.strip(), self.context.strip()) if p]
        return "\n\n".join(parts)


def _parse_turn(raw: Any, path: Path, idx: int) -> Turn:
    if not isinstance(raw, dict) or not isinstance(raw.get("say"), str) or not raw["say"].strip():
        raise ScenarioError(f"{path}: turns[{idx}] cần 'say' là chuỗi khác rỗng")
    expect_raw = raw.get("expect") or {}
    if not isinstance(expect_raw, dict):
        raise ScenarioError(f"{path}: turns[{idx}].expect phải là map")
    tag = expect_raw.get("tag")
    if tag is not None and tag not in VALID_TAGS:
        raise ScenarioError(
            f"{path}: turns[{idx}].expect.tag={tag!r} không hợp lệ (chọn {VALID_TAGS} hoặc bỏ trống)"
        )
    expect = Expect(tag=tag, reply_nonempty=bool(expect_raw.get("reply_nonempty", True)))
    return Turn(say=raw["say"], expect=expect)


def _resolve_call_scripts(entries: list[str], base_dir: Path) -> tuple[str, ...]:
    """Nạp danh sách call script. Entry là đường dẫn file/thư mục (tương đối theo
    `base_dir`) → đọc nội dung; thư mục → mọi file .txt bên trong (sắp theo tên).
    Text thuần giữ nguyên làm mẫu inline."""
    out: list[str] = []
    for entry in entries:
        candidate = Path(entry)
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        if candidate.is_dir():
            for p in sorted(candidate.glob("*.txt")):
                text = p.read_text(encoding="utf-8")
                if text.strip():
                    out.append(text)
        elif candidate.is_file():
            out.append(candidate.read_text(encoding="utf-8"))
        else:
            out.append(entry)
    return tuple(out)


# ---------- profile bot ----------


def _find_profile_file(start: Path) -> Path | None:
    """Tìm profile.yaml của bot — đi lên từ file kịch bản (bots/<bot>/scenarios/ → bots/<bot>/)."""
    for parent in [start, *start.parents][:4]:
        candidate = parent / "profile.yaml"
        if candidate.is_file():
            return candidate
    return None


def load_profile(profile_path: str | Path) -> dict:
    """Đọc và validate một file profile; trả dict thô đã khớp dạng."""
    profile_path = Path(profile_path)
    if not profile_path.is_file():
        raise ScenarioError(f"không tìm thấy profile: {profile_path}")
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ScenarioError(f"{profile_path}: profile phải là map")
    for key in ("business", "business_file", "display_name"):
        if key in data and not isinstance(data[key], str):
            raise ScenarioError(f"{profile_path}: '{key}' phải là chuỗi")
    if data.get("business") and data.get("business_file"):
        raise ScenarioError(
            f"{profile_path}: chỉ dùng MỘT trong 'business' / 'business_file'"
        )
    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ScenarioError(f"{profile_path}: 'defaults' phải là map")
    scripts = data.get("call_scripts") or []
    if not isinstance(scripts, list) or not all(isinstance(s, str) for s in scripts):
        raise ScenarioError(f"{profile_path}: 'call_scripts' phải là danh sách chuỗi")
    return data


def profile_file_for(scenario_path: Path) -> Path | None:
    return _find_profile_file(Path(scenario_path).parent)


def _apply_profile(scenario: Scenario, raw: dict, prof_path: Path | None) -> Scenario:
    """Áp profile bot: điền target/max_turns nếu kịch bản chưa khai; gộp persona;
    nối call_scripts (resolve theo thư mục profile); nghiệp vụ nền — inline
    `business` hoặc file `business_file` trong knowledge/ — vào `business`
    (giữ `context` riêng của kịch bản).

    Kịch bản nằm dưới `profile.yaml` thì tự kế thừa; khai tường minh
    `profile: <bot>` chỉ để tự ghi rõ, tên phải khớp `bot:`."""
    if prof_path is None:
        raise ScenarioError(
            f"{scenario.path}: khai profile {scenario.profile!r} nhưng không thấy profile.yaml nào ở trên cây thư mục"
        )
    prof = load_profile(prof_path)
    bot = str(prof.get("bot") or "")
    if scenario.profile and scenario.profile != bot:
        raise ScenarioError(
            f"{scenario.path}: khai profile {scenario.profile!r} nhưng {prof_path} là của bot {bot!r}"
        )
    base_dir = prof_path.parent
    business = str(prof.get("business") or "")
    if prof.get("business_file"):
        bf = Path(prof["business_file"])
        if not bf.is_absolute():
            bf = base_dir / bf
        if not bf.is_file():
            raise ScenarioError(f"{prof_path}: business_file {prof['business_file']!r} không tồn tại")
        business = bf.read_text(encoding="utf-8")
    defaults = prof.get("defaults") or {}
    persona = {**(defaults.get("persona") or {}), **scenario.persona}
    return Scenario(
        **{
            **scenario.__dict__,
            "target": scenario.target or str(prof.get("target") or ""),
            "persona": persona,
            "max_turns": scenario.max_turns if scenario.max_turns is not None else defaults.get("max_turns"),
            "call_scripts": _resolve_call_scripts(prof.get("call_scripts") or [], base_dir)
            + scenario.call_scripts,
            "business": business,
        }
    )


# ---------- tình huống (mix được vào kịch bản llm) ----------


@dataclass(frozen=True)
class Situation:
    """Một tình huống tái sử dụng (bots/<bot>/situations/<tên>.yaml).

    Fragment nghiệp vụ, không phải kịch bản: không mode/target/turns.
    Khi được `mix:`, goal/context nối vào kịch bản, forbidden_phrases hợp lại,
    persona gộp (tình huống thắng), extra_turns cộng vào ngân sách lượt.
    """

    name: str
    goal: str = ""
    context: str = ""
    persona: dict[str, Any] = field(default_factory=dict)
    forbidden_phrases: tuple[str, ...] = ()
    call_scripts: tuple[str, ...] = ()
    extra_turns: int = 0


def _load_situation(path: Path) -> Situation:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ScenarioError(f"{path}: tình huống phải là map")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ScenarioError(f"{path}: tình huống cần 'name' là chuỗi khác rỗng")
    for key in ("goal", "context"):
        if data.get(key) is not None and not isinstance(data[key], str):
            raise ScenarioError(f"{path}: '{key}' phải là chuỗi")
    persona = data.get("persona") or {}
    if not isinstance(persona, dict):
        raise ScenarioError(f"{path}: 'persona' phải là map")
    phrases = data.get("forbidden_phrases") or []
    if not isinstance(phrases, list) or not all(isinstance(p, str) and p.strip() for p in phrases):
        raise ScenarioError(f"{path}: 'forbidden_phrases' phải là danh sách chuỗi khác rỗng")
    extra = data.get("extra_turns", 0)
    if not isinstance(extra, int) or isinstance(extra, bool) or extra < 0:
        raise ScenarioError(f"{path}: 'extra_turns' phải là số nguyên >= 0")
    scripts = data.get("call_scripts") or []
    if not isinstance(scripts, list) or not all(isinstance(s, str) for s in scripts):
        raise ScenarioError(f"{path}: 'call_scripts' phải là danh sách chuỗi")
    return Situation(
        name=name,
        goal=str(data.get("goal") or ""),
        context=str(data.get("context") or ""),
        persona=persona,
        forbidden_phrases=tuple(phrases),
        call_scripts=tuple(scripts),
        extra_turns=extra,
    )


def _apply_mix(scenario: Scenario, situations_dir: Path) -> Scenario:
    """Gộp các tình huống trong `mix` vào kịch bản mode llm — một cuộc gọi,
    nhiều tình huống đan nhau. Thứ tự trộn = thứ tự khai trong `mix`."""
    parts: list[Situation] = []
    for name in scenario.mix:
        path = situations_dir / f"{name}.yaml"
        if not path.is_file():
            raise ScenarioError(f"{scenario.path}: mix '{name}' không có file {path}")
        parts.append(_load_situation(path))

    goal = scenario.goal or ""
    additions = [f"- [{s.name}] {s.goal.strip()}" for s in parts if s.goal.strip()]
    if additions:
        goal = (
            goal.rstrip()
            + "\n\nTình huống kèm theo (xử lý trọn trong cùng cuộc gọi):\n"
            + "\n".join(additions)
        )

    context = scenario.context.rstrip()
    for s in parts:
        if s.context.strip():
            block = f"Luật từ tình huống [{s.name}]:\n{s.context.strip()}"
            context = f"{context}\n\n{block}" if context else block

    phrases: list[str] = list(scenario.forbidden_phrases)
    for s in parts:
        for p in s.forbidden_phrases:
            if p not in phrases:
                phrases.append(p)

    persona = dict(scenario.persona)
    for s in parts:
        persona.update(s.persona)

    scripts = scenario.call_scripts + tuple(
        x
        for s in parts
        for x in _resolve_call_scripts(list(s.call_scripts), situations_dir.parent)
    )
    extra = sum(s.extra_turns for s in parts)
    return Scenario(
        **{
            **scenario.__dict__,
            "goal": goal,
            "context": context,
            "forbidden_phrases": tuple(phrases),
            "persona": persona,
            "call_scripts": scripts,
            "max_turns": scenario.max_turns + extra if scenario.max_turns is not None else None,
        }
    )


# ---------- kịch bản ----------


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path)
    if not path.exists():
        raise ScenarioError(f"không tìm thấy kịch bản: {path}")
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ScenarioError(f"{path}: kịch bản phải là map")

    profile = raw.get("profile")
    target = str(raw.get("target") or "")
    if not target.strip() and not str(profile or "").strip() and _find_profile_file(path.parent) is None:
        raise ScenarioError(
            f"{path}: cần 'target' (tên trong config.yaml), 'profile', hoặc nằm dưới profile.yaml của bot"
        )
    mode = raw.get("mode", "script")
    if mode not in VALID_MODES:
        raise ScenarioError(f"{path}: mode {mode!r} không hợp lệ (chọn {VALID_MODES})")
    persona = raw.get("persona") or {}
    if not isinstance(persona, dict):
        raise ScenarioError(f"{path}: 'persona' phải là map")
    phrases = raw.get("forbidden_phrases") or []
    if not isinstance(phrases, list) or not all(isinstance(p, str) and p.strip() for p in phrases):
        raise ScenarioError(f"{path}: 'forbidden_phrases' phải là danh sách chuỗi khác rỗng")

    base = Scenario(
        path=path,
        suite=str(raw.get("suite") or path.stem),
        name=str(raw.get("name") or path.stem),
        target=target,
        mode=mode,
        profile=str(profile) if profile else None,
        persona=persona,
        forbidden_phrases=tuple(phrases),
    )

    if mode == "script":
        if raw.get("mix"):
            raise ScenarioError(f"{path}: 'mix' chỉ dùng cho mode llm (script có turns cố định)")
        turns_raw = raw.get("turns")
        if not isinstance(turns_raw, list) or not turns_raw:
            raise ScenarioError(f"{path}: mode script cần 'turns' là danh sách không rỗng")
        result = Scenario(**{**base.__dict__, "turns": tuple(_parse_turn(t, path, i) for i, t in enumerate(turns_raw))})
    else:
        goal = raw.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            raise ScenarioError(f"{path}: mode llm cần 'goal' là chuỗi mô tả mục tiêu cuộc gọi")
        max_turns = raw.get("max_turns")
        if max_turns is not None and (not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1):
            raise ScenarioError(f"{path}: 'max_turns' phải là số nguyên >= 1")
        if raw.get("turns"):
            raise ScenarioError(f"{path}: mode llm không dùng 'turns' cố định — hãy mô tả bằng 'goal'")
        context = raw.get("context") or ""
        if not isinstance(context, str):
            raise ScenarioError(f"{path}: 'context' phải là chuỗi (tài liệu/rubric)")
        scripts_raw = raw.get("call_scripts") or []
        if not isinstance(scripts_raw, list) or not all(isinstance(s, str) and s.strip() for s in scripts_raw):
            raise ScenarioError(f"{path}: 'call_scripts' phải là danh sách đường dẫn .txt hoặc chuỗi văn phong")
        mix_raw = raw.get("mix") or []
        if not isinstance(mix_raw, list) or not all(isinstance(m, str) and m.strip() for m in mix_raw):
            raise ScenarioError(f"{path}: 'mix' phải là danh sách tên tình huống (situations/*.yaml)")
        result = Scenario(
            **{
                **base.__dict__,
                "goal": goal,
                "max_turns": max_turns,
                "context": context,
                "call_scripts": _resolve_call_scripts(scripts_raw, path.parent),
                "mix": tuple(mix_raw),
            }
        )

    prof_path = _find_profile_file(path.parent)
    if prof_path is not None or result.profile:
        result = _apply_profile(result, raw, prof_path)
    if result.mix:
        if prof_path is None:
            raise ScenarioError(
                f"{path}: 'mix' cần bot có profile.yaml (thư mục situations/ nằm cạnh nó)"
            )
        result = _apply_mix(result, prof_path.parent / "situations")
    if result.mode == "llm" and result.max_turns is None:
        raise ScenarioError(f"{path}: mode llm cần 'max_turns' (trực tiếp hoặc qua profile defaults)")
    if not result.target:
        raise ScenarioError(f"{path}: thiếu target sau khi áp profile (profile chưa khai 'target')")
    return result


def load_suite(pattern: str | Path) -> list[Scenario]:
    """Nạp mọi kịch bản khớp glob (tuyệt đối hoặc tương đối), sắp theo id để chạy deterministic."""
    matches = sorted(Path(p) for p in _glob.glob(str(pattern)))
    scenarios = [load_scenario(p) for p in matches if p.is_file()]
    if not scenarios:
        raise ScenarioError(f"không có kịch bản nào khớp: {pattern}")
    return sorted(scenarios, key=lambda s: s.id)
