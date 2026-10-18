"""各层之间传递的数据结构。

依据：规格 §3.2。这里只有数据：没有输入输出，没有业务判断。
三条数据接缝（§2.0）：`MeasureTask`/`MeasureResult`（L3→L2）、`IR`（L3→L4）、
`ProviderCapabilities`（L1→L2，定义在 providers/base.py，因此不在这里）。

`Crop.has_clef` 是 RD-04 的闸门：不含谱号区的裁片禁止送出，所以这个字段必须有，
而且必须是真正的布尔值，不能被字符串之类的真值混过去。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .errors import ErrorCode
from .ir import Beat, Judgement, KeySignature, SkeletonProvenance, Tempo, TimeSignature

__all__ = [
    "Crop",
    "Judgement",
    "MeasureBox",
    "MeasureRead",
    "MeasureResult",
    "MeasureTask",
    "Page",
    "PageSet",
    "Skeleton",
    "System",
]


class _Model(BaseModel):
    """中间结构的共同约定：不许出现规格外的字段，别名字段也能按字段名构造。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MeasureBox(_Model):
    """页面上一个小节的横向范围，坐标是原图像素。"""

    index: int
    printed: int | None = None
    x0: float
    x1: float
    width: float


class System(_Model):
    """一个系统：上面五线谱带，下面 TAB 带，外加谱号区的横向范围。"""

    id: int
    page: int
    y0: float
    y1: float
    tabY0: float
    tabY1: float
    tabLines: list[float] = Field(default_factory=list)
    measures: list[MeasureBox] = Field(default_factory=list)
    headerX0: float
    headerX1: float


class Page(_Model):
    path: str
    width: int
    height: int
    deg: float
    systems: list[System] = Field(default_factory=list)


class PageSet(_Model):
    pages: list[Page] = Field(default_factory=list)
    class_: int = Field(alias="class")
    degGlobal: float


class Crop(_Model):
    """一张送给模型的裁片。

    `has_clef` 标记这张裁片有没有包含完整的谱号区；为 False 时禁止送出（RD-04）。
    """

    path: str
    box: list[int | float] = Field(min_length=4, max_length=4)
    kind: Literal["system", "reread", "sheet"]
    px: int
    deg: float
    has_clef: StrictBool


class MeasureTask(_Model):
    """S-IF1：L3 给 L2 的一次读取任务。"""

    system: int
    measures: list[MeasureBox] = Field(default_factory=list)
    crop: Crop
    hints: dict[str, Any] = Field(default_factory=dict)
    callId: str


class MeasureRead(_Model):
    """S-IF1：单个小节的结构化事实。"""

    index: int
    beats: list[Beat] = Field(default_factory=list)
    unreadable: bool = False
    # 谱面上印的小节号（没有就是 None）；装配时印刷号优先、累加兜底（AS-03）。
    printed: int | None = None
    # 多小节休止的条数；普通小节为 1（AS-01）。
    multiRest: int = 1


class MeasureResult(_Model):
    """S-IF1：一次调用的结果。接口粒度是小节，传输粒度是系统（§2.4）。"""

    callId: str
    reads: list[MeasureRead] = Field(default_factory=list)
    usage: dict[str, Any] | None = None
    errorCode: ErrorCode | None = None


class Skeleton(_Model):
    """骨架：全局参数，每项都带来源（§2.2 的分级读取）。"""

    timeSignatures: list[TimeSignature] = Field(default_factory=list)
    keySignatures: list[KeySignature] = Field(default_factory=list)
    tempos: list[Tempo] = Field(default_factory=list)
    tuning: list[int]
    stringCount: int
    title: str
    artist: str
    provenance: SkeletonProvenance
    # 低音谱号固定下移 12 个半音；品数上限默认 24，不读取（§3.1、A3）。
    clefTranspose: int = -12
    fretCount: int = 24
