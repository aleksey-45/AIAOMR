"""骨架读取（规格 §2.2）：分级读全局参数，缺项兜底并记来源。

S-01：骨架必须由视觉调用产出；P0–P3 缺项按兜底值补，**禁止**因缺项失败。
S-04/S-05：拍号/调号是事件列表，续行系统没印时**继承**上一值，"没印"不等于"变化"。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...kernel.config import Config
from ...kernel.contracts import Crop, Skeleton
from ...kernel.ir import KeySignature, SkeletonProvenance, Tempo, TimeSignature
from ...providers.base import ImageInput, ProviderError, VisionRequest

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "skeleton.md"

# 标准调弦：4/5/6 弦，MIDI，低音弦在前。
_STANDARD_TUNING = {4: [28, 33, 38, 43], 5: [23, 28, 33, 38, 43], 6: [23, 28, 33, 38, 43, 48]}


class HeaderFacts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timeSignature: dict | None = None
    keySignature: str | None = None
    tempo: int | None = Field(default=None, ge=20, le=320)
    tuning: list[int] | None = None
    stringCount: int | None = Field(default=None, ge=4, le=6)
    title: str | None = None
    artist: str | None = None


def load_prompt(version: str = "p0") -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").replace("{{promptVersion}}", version)


def parse_facts(raw: str) -> HeaderFacts:
    """严格解析模型输出；失败抛 `ValueError`（带截断原因）。"""
    if not raw or not raw.strip():
        raise ValueError("骨架返回为空")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 无法解析：{exc.msg}") from exc
    try:
        return HeaderFacts.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"结构不符：{exc.errors()[0].get('msg', '')}") from exc


def default_skeleton(
    title: str,
    string_count: int = 4,
    default_key: str = "CMajor",
    default_tempo: int = 120,
) -> Skeleton:
    return Skeleton(
        timeSignatures=[],
        keySignatures=[KeySignature(measure=1, key=default_key)],
        tempos=[Tempo(measure=1, bpm=default_tempo)],
        tuning=list(_STANDARD_TUNING.get(string_count, _STANDARD_TUNING[4])),
        stringCount=string_count,
        title=title,
        artist="",
        clefTranspose=-12,
        fretCount=24,
        provenance=SkeletonProvenance(
            timeSignatures="defaulted",
            tuning="derived",
            keySignatures="defaulted",
            tempos="defaulted",
            title="filename",
            artist="empty",
        ),
    )


def normalize_key(value: str) -> str:
    """把模型写的调号规范成 Guitar Pro 的名字：`Bb major` → `BbMajor`、`F# minor` → `F#Minor`。"""
    text = value.strip()
    match = re.match(r"^([A-Ga-g])([#b]?)\s*(major|minor)$", text)
    if not match:
        return text
    note = match.group(1).upper() + match.group(2)
    mode = "Major" if match.group(3).lower() == "major" else "Minor"
    return note + mode


def _fill_initial(skel: Skeleton, facts: HeaderFacts, cfg: Config) -> Skeleton:
    """把首页读到的东西填进骨架；缺项按 §2.2.1 兜底。"""
    tuning = facts.tuning
    if tuning and 4 <= len(tuning) <= 6 and all(
        later > earlier for earlier, later in zip(tuning, tuning[1:])
    ):
        skel.tuning = list(tuning)
        skel.stringCount = len(tuning)
        skel.provenance.tuning = "read"
    elif facts.stringCount and facts.stringCount in _STANDARD_TUNING:
        skel.stringCount = facts.stringCount
        skel.tuning = list(_STANDARD_TUNING[facts.stringCount])
        skel.provenance.tuning = "derived"

    signature = facts.timeSignature
    if signature and isinstance(signature, dict):
        beats = int(signature.get("beats", 0) or 0)
        beat_type = int(signature.get("beatType", 0) or 0)
        if beats > 0 and beat_type > 0:
            skel.timeSignatures = [TimeSignature(measure=1, beats=beats, beatType=beat_type)]
            skel.provenance.timeSignatures = "read"

    if facts.keySignature:
        key = normalize_key(facts.keySignature)
        skel.keySignatures = [KeySignature(measure=1, key=key)]
        skel.provenance.keySignatures = "read"

    if facts.tempo:
        skel.tempos = [Tempo(measure=1, bpm=int(facts.tempo))]
        skel.provenance.tempos = "read"

    if facts.title and facts.title.strip():
        skel.title = facts.title.strip()
        skel.provenance.title = "read"
    if facts.artist and facts.artist.strip():
        skel.artist = facts.artist.strip()
        skel.provenance.artist = "read"
    return skel


def apply_ts_inference(skel: Skeleton, bar_durations: list[int], min_measures: int = 3) -> Skeleton:
    """拍号读不出来时，用各小节时值的众数回填，来源标 `inferred`（§2.2.1 P0）。"""
    if skel.provenance.timeSignatures == "read":
        return skel
    durations = [value for value in bar_durations if value > 0]
    if len(durations) < min_measures:
        return skel
    values, counts = _mode(durations)
    if values is None:
        return skel
    if values not in (2, 3, 4, 5, 6, 7, 8, 9, 12):
        return skel
    skel.timeSignatures = [TimeSignature(measure=1, beats=values, beatType=4)]
    skel.provenance.timeSignatures = "inferred"
    return skel


def apply_header(skel: Skeleton, facts: HeaderFacts, measure: int) -> Skeleton:
    """某个系统头部读到的变化点；没印的项是 null，继承上一值，不生成变化事件（S-05）。"""
    signature = facts.timeSignature
    if signature and isinstance(signature, dict):
        beats = int(signature.get("beats", 0) or 0)
        beat_type = int(signature.get("beatType", 0) or 0)
        if beats > 0 and beat_type > 0:
            last = skel.timeSignatures[-1] if skel.timeSignatures else None
            if last is None or (last.beats, last.beatType) != (beats, beat_type):
                skel.timeSignatures.append(
                    TimeSignature(measure=measure, beats=beats, beatType=beat_type)
                )
    if facts.keySignature:
        key = normalize_key(facts.keySignature)
        last = skel.keySignatures[-1] if skel.keySignatures else None
        if last is None or last.key != key:
            skel.keySignatures.append(KeySignature(measure=measure, key=key))
    if facts.tempo:
        last = skel.tempos[-1] if skel.tempos else None
        if last is None or last.bpm != facts.tempo:
            skel.tempos.append(Tempo(measure=measure, bpm=int(facts.tempo)))
    return skel


def read_skeleton(
    header_crop: Crop,
    provider,
    cfg: Config,
    emit=None,
    hints: dict | None = None,
) -> Skeleton:
    """读首页头部：拍号、调号、调弦、弦数、速度、曲名、作者。"""
    hints = hints or {}
    path = Path(header_crop.path)
    title = hints.get("title") or (path.stem if cfg.skeleton.title_from_filename else "")
    skeleton = default_skeleton(
        title,
        int(hints.get("stringCount", 4)),
        default_key=cfg.skeleton.default_key,
        default_tempo=cfg.skeleton.default_tempo,
    )

    if emit is not None:
        emit("skeleton", "skeleton.started", callId=hints.get("callId", "skeleton"))
    if not path.exists():
        raise FileNotFoundError(path)

    request = VisionRequest(
        call_id=hints.get("callId", "skeleton"),
        prompt_prefix=load_prompt(),
        prompt_suffix=(
            f"这是第 {hints.get('page', 1)} 页第一个系统的头部；"
            f"TAB 有 {hints.get('stringCount', 4)} 条线。"
        ),
        images=(ImageInput(path.read_bytes(), "image/png"),),
        max_tokens=1500,
        thinking=False,
    )
    try:
        response = provider.read(request)
        facts = parse_facts(response.content)
        skeleton = _fill_initial(skeleton, facts, cfg)
        if emit is not None:
            emit("skeleton", "skeleton.done", title=skeleton.title)
    except (ProviderError, ValueError, FileNotFoundError) as exc:
        # S-01：失败不阻断，按兜底值继续；错误留给上层记事件
        if emit is not None:
            emit("skeleton", "skeleton.failed", error=str(exc)[:300])
    return skeleton


def _mode(values: list[int]) -> tuple[int | None, int]:
    counts: dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return None, 0
    best = max(counts.items(), key=lambda item: item[1])
    return best[0], best[1]
