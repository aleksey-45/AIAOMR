"""几何节奏：把几何判据的结论装配成"每拍是什么时值"（P2 任务 2）。

判据本身在 `score/geometry/criteria.py`：符干、连梁、符尾、附点、休止条各管一件事。
这里只做装配：一根符干 = 一拍；连梁/符尾条数决定八/十六/三十二分；附点乘 1.5；
加起来对不上拍号就整小节退回 `unknown`，不硬凑。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ...kernel.contracts import MeasureBox, System
from ..geometry.context import measure_context
from ..geometry.criteria import (
    BeamCriterion,
    DotCriterion,
    FlagCriterion,
    RestBarCriterion,
    StemCriterion,
)

# 1/32 拍为 1 tick（quarter = 8）。
TICKS = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2, "32nd": 1}


@dataclass
class BeatShape:
    x: float
    duration: str
    dots: int = 0
    kind: str = "note"
    evidence: dict = field(default_factory=dict)

    @property
    def ticks(self) -> int:
        if self.kind == "rest":
            return 0
        return int(round(TICKS.get(self.duration, 0) * (1.5 if self.dots == 1 else 1.0)))


def _nearest_stem(stems, x: float):
    if not stems:
        return None
    return min(stems, key=lambda stem: abs(stem.value - x))


def read_measure_rhythm(
    arr: np.ndarray,
    system: System,
    measure_box: MeasureBox,
    deg: float,
    expected_ticks: int | None = None,
) -> list[BeatShape]:
    """一个小节的时值候选；`unknown` 表示这块交给模型/复读。"""
    ctx = measure_context(arr, system, measure_box, deg)
    if ctx.dark.size == 0:
        return []

    findings: dict[str, list] = {}
    for criterion in (StemCriterion(),):
        findings[criterion.name] = criterion.detect(ctx, findings)
    stems = findings["stem"]

    if not stems:
        if RestBarCriterion().detect(ctx, findings):
            return [
                BeatShape(
                    x=ctx.left + ctx.width / 2,
                    duration="whole",
                    kind="rest",
                    evidence={"detected": "rest_bar"},
                )
            ]
        ink = int(ctx.dark.sum())
        center = ctx.left + ctx.width / 2
        if ink < 0.6 * deg * deg:
            return [BeatShape(x=center, duration="whole", kind="rest")]
        return [BeatShape(x=center, duration="whole", kind="note",
                          evidence={"detected": "no-stem", "ink": ink})]

    findings["beam"] = BeamCriterion().detect(ctx, findings)
    findings["flag"] = FlagCriterion().detect(ctx, findings)
    findings["dot"] = DotCriterion().detect(ctx, findings)

    beam_count: dict[float, int] = {}
    for beam in findings["beam"]:
        for key in (beam.bbox[0], beam.bbox[2]):
            beam_count[key] = max(beam_count.get(key, 0), int(beam.value))

    flags: dict[float, int] = {}
    for flag in findings["flag"]:
        stem = _nearest_stem(stems, flag.bbox[0] - 1)
        if stem is not None:
            flags[stem.value] = max(flags.get(stem.value, 0), int(flag.value))

    dots: set[float] = set()
    for dot in findings["dot"]:
        stem = _nearest_stem(stems, (dot.bbox[0] + dot.bbox[2]) / 2 - 0.6 * deg)
        if stem is not None:
            dots.add(stem.value)

    shapes: list[BeatShape] = []
    for stem in stems:
        count = beam_count.get(stem.value, 0) or flags.get(stem.value, 0)
        duration = {0: "quarter", 1: "eighth", 2: "16th", 3: "32nd"}.get(count, "unknown")
        shapes.append(
            BeatShape(
                x=stem.value + ctx.left,
                duration=duration,
                dots=1 if stem.value in dots else 0,
                evidence={"stem_top": stem.bbox[1], "stem_bottom": stem.bbox[3], "beams": count},
            )
        )

    if expected_ticks is not None:
        total = sum(shape.ticks for shape in shapes)
        if total != expected_ticks:
            for shape in shapes:
                shape.duration = "unknown"
                shape.dots = 0
    return shapes


def read_system_rhythm(
    arr: np.ndarray,
    system: System,
    deg: float,
    expected_ticks_by_measure: dict[int, int] | None = None,
) -> dict[int, list[BeatShape]]:
    """整个系统的时值候选，按小节号索引。"""
    result: dict[int, list[BeatShape]] = {}
    for box in system.measures:
        expected = None if expected_ticks_by_measure is None else expected_ticks_by_measure.get(box.index)
        result[box.index] = read_measure_rhythm(arr, system, box, deg, expected)
    return result
