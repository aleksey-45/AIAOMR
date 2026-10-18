"""模型返回的小节读数：结构校验（规格 §2.3.1 的 G2/G3 两道闸）。

`validate` 先做严格 `json.loads`（G2，禁止用正则抠），再用 pydantic 校验形状（G3）。
业务判断（A1–A12）不在这里，属于验算层。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..kernel.ir import Duration

__all__ = ["ModelBeat", "ModelMeasure", "ModelNote", "ModelResponse", "SchemaError", "validate"]


class SchemaError(ValueError):
    """模型输出没通过结构校验；消息已截断，可以直接回给模型（V-05b）。"""


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ModelNote(_Model):
    string: int = Field(ge=1, le=6)
    fret: int = Field(ge=0, le=36)
    pitch: int = Field(ge=0, le=127)
    digit: str | None = None
    tie: bool = False
    tieFromPrevious: bool = False


class ModelBeat(_Model):
    duration: Duration
    dots: int = Field(default=0, ge=0, le=2)
    rest: bool = False
    notes: list[ModelNote] = Field(default_factory=list)


class ModelMeasure(_Model):
    index: int = Field(ge=1)
    beats: list[ModelBeat] = Field(default_factory=list)
    unreadable: bool = False


class ModelResponse(_Model):
    measures: list[ModelMeasure]


def validate(raw: str) -> ModelResponse:
    """严格解析并校验；失败抛 `SchemaError`（带截断后的原因）。"""
    if not raw or not raw.strip():
        raise SchemaError("模型返回为空")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SchemaError(f"JSON 无法解析：{exc.msg} at {exc.pos}") from exc
    try:
        return ModelResponse.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        raise SchemaError(f"结构不符：{location}: {first.get('msg', '')}"[:500]) from exc
