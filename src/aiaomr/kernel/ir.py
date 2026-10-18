"""IR（中间数据结构）v3.0：L3 交给 L4 的唯一交付契约。

依据：规格 §3.1。字段名与 §3.1 的 JSON 逐字对齐，`kernel/ir.py` 是唯一 schema 来源。

两处要点：

- `Score.measureCount` 是计算字段：不单独存值，序列化时由 `IR` 写进 JSON；
  读入时如果给了这个值又不等于 `len(measures)`，报校验错误（§3.1 不变量）。
- `to_json` 先写 `.tmp` 再 `os.replace`，进程被杀也不会留下半个文件。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

# 时值取值照规格 §3.1。
Duration = Literal["whole", "half", "quarter", "eighth", "16th", "32nd"]


class _Model(BaseModel):
    """内核数据类的共同约定：不许出现规格外的字段，别名字段也能按字段名构造。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Meta(_Model):
    provider: str
    model: str
    promptVersion: str
    schemaVersion: str = "3.0"
    generatedAt: datetime


class Source(_Model):
    class_: int = Field(alias="class")
    kind: str
    files: list[str] = Field(default_factory=list)
    inputSha256: str


class TimeSignature(_Model):
    measure: int
    beats: int
    beatType: int


class KeySignature(_Model):
    measure: int
    key: str


class Tempo(_Model):
    measure: int
    bpm: int


class SkeletonProvenance(_Model):
    timeSignatures: Literal["read", "inferred", "defaulted"]
    tuning: Literal["read", "derived"]
    keySignatures: Literal["read", "defaulted"]
    tempos: Literal["read", "defaulted"]
    title: Literal["read", "filename"]
    artist: Literal["read", "empty"]


class Digit(_Model):
    """谱面上印的那个数字：`12` 是一个数字、两个字形（§6.1 A4）。"""

    value: str
    glyphs: int
    bound: bool


class Evidence(_Model):
    system: int
    crop: list[int | float] = Field(min_length=4, max_length=4)
    call: str


class Note(_Model):
    string: int
    fret: int
    tie: bool = False
    tieFromPrevious: bool = False
    digit: Digit | None = None
    techniques: list[str] = Field(default_factory=list)
    pitch: int
    pitchClaim: int | None = None


class Beat(_Model):
    duration: Duration
    dots: Literal[0, 1, 2] = 0
    rest: bool = False
    notes: list[Note] = Field(default_factory=list)
    prov: Literal["read", "derived"] = "read"
    evidence: Evidence


class Measure(_Model):
    index: int = Field(ge=1)
    printed: int | None = None
    rest: bool = False
    multiRest: int = 1
    beats: list[Beat] = Field(default_factory=list)


class Repeat(_Model):
    start: int
    end: int
    times: int


class Ending(_Model):
    measure: int
    number: int


class Jump(_Model):
    type: str
    measure: int


class Section(_Model):
    measure: int
    label: str


class Structure(_Model):
    repeats: list[Repeat] = Field(default_factory=list)
    endings: list[Ending] = Field(default_factory=list)
    jumps: list[Jump] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)


class Judgement(_Model):
    """终裁记录（§2.6 AD-04、§3.1）。

    规格 §3.2 把它列在中间结构里，字段却标着"见 IR"，所以定义留在 ir.py，
    由 contracts.py 转出，保证只有一份 schema。
    """

    id: str
    measure: int
    rule: str
    claimed: int | float
    expected: int | float
    final: int | float | None = None
    reason: str
    model: str
    promptVersion: str
    crops: list[str] = Field(default_factory=list)
    ts: datetime


class Audit(_Model):
    pitchMismatch: int
    barErrors: int


class Build(_Model):
    gp5: str
    roundtrip: str
    audit: Audit


class Score(_Model):
    title: str = ""
    artist: str = ""
    tabber: str = ""
    # MIDI 音高，低音弦在前，长度必须等于弦数。
    tuning: list[int]
    stringCount: int
    timeSignatures: list[TimeSignature] = Field(default_factory=list)
    keySignatures: list[KeySignature] = Field(default_factory=list)
    tempos: list[Tempo] = Field(default_factory=list)
    clefTranspose: int
    fretCount: int

    @field_validator("tuning")
    @classmethod
    def _tuning_must_be_strictly_increasing(cls, value: list[int]) -> list[int]:
        if any(later <= earlier for earlier, later in zip(value, value[1:])):
            raise ValueError("tuning 必须严格递增（低音弦在前），不能相等或倒序")
        return value

    @model_validator(mode="after")
    def _tuning_length_must_match_string_count(self) -> "Score":
        if len(self.tuning) != self.stringCount:
            raise ValueError(
                f"tuning 长度 {len(self.tuning)} 必须等于 stringCount {self.stringCount}"
            )
        return self

    @field_validator("timeSignatures", "keySignatures", "tempos")
    @classmethod
    def _event_measures_must_be_strictly_increasing(cls, value: list) -> list:
        numbers = [entry.measure for entry in value]
        if any(later <= earlier for earlier, later in zip(numbers, numbers[1:])):
            raise ValueError("measure 必须严格递增，且每条表示从该小节起生效")
        return value


class IR(_Model):
    version: Literal["3.0"] = "3.0"
    meta: Meta
    source: Source
    score: Score
    skeletonProvenance: SkeletonProvenance
    measures: list[Measure] = Field(default_factory=list)
    structure: Structure = Field(default_factory=Structure)
    judgements: list[Judgement] = Field(default_factory=list)
    build: Build | None = None

    @model_validator(mode="before")
    @classmethod
    def _verify_measure_count(cls, data: object) -> object:
        """`measureCount` 只是序列化出来的计算字段，读入时最多用来核对。"""
        if not isinstance(data, dict):
            return data
        score = data.get("score")
        if not isinstance(score, dict) or "measureCount" not in score:
            return data
        score = dict(score)
        claimed = score.pop("measureCount")
        measures = data.get("measures") or []
        if claimed != len(measures):
            raise ValueError(
                f"score.measureCount={claimed} 与实际小节条数 {len(measures)} 不一致；"
                "measureCount 是计算字段，取 len(measures)"
            )
        return {**data, "score": score}

    @model_serializer(mode="wrap")
    def _write_measure_count(self, handler):
        """小节总数不存值，序列化时才按实际条数写出来。"""
        data = handler(self)
        score = data.get("score")
        if isinstance(score, dict):
            score["measureCount"] = len(data.get("measures") or [])
        return data

    def to_json(self, path: str | Path) -> Path:
        """原子写：先写同目录下的 `.tmp`，落盘后再改名覆盖。"""
        target = Path(path)
        text = json.dumps(
            self.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            indent=2,
        )
        temporary = target.with_name(target.name + ".tmp")
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return target

    @classmethod
    def from_json(cls, path: str | Path) -> "IR":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
