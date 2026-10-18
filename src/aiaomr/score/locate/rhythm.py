"""几何节奏：从符干、符尾（连梁/小钩）、附点量出每一拍的时值（规格 §2.1 R-03、P2 任务 2）。

只出候选，不出结论：数不准的拍标 `unknown`，交给模型/复读；整小节加起来对不上拍号时，
整小节退回 `unknown`，不许硬凑。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ...kernel.contracts import MeasureBox, System
from .systems import adaptive_cut, staff_lines

# 1/32 拍为 1 tick（quarter = 8）。
TICKS = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2, "32nd": 1}
_STEM_MIN = 2.0      # 符干最短（deg 倍数）
_STEM_MAX = 5.5      # 符干最长
_BEAM_COVERAGE = 0.85


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


def _stems(dark: np.ndarray, deg: float, width: int) -> list[tuple[float, int, int]]:
    """竖直线段 → (x, top, bottom)；排除小节线（贴着左右边缘、高度接近整条谱表）。"""
    height = dark.shape[0]
    candidates: list[tuple[float, int, int]] = []
    for x in range(width):
        column = dark[:, x]
        best_run = None
        start = None
        last = None
        for y in range(height):
            if column[y]:
                if start is None:
                    start = last = y
                elif y - last <= 3:
                    last = y
                else:
                    if best_run is None or (last - start) > (best_run[1] - best_run[0]):
                        best_run = (start, last)
                    start = last = y
            else:
                if start is not None and y - last > 2:
                    if best_run is None or (last - start) > (best_run[1] - best_run[0]):
                        best_run = (start, last)
                    start = None
        if start is not None:
            if best_run is None or (last - start) > (best_run[1] - best_run[0]):
                best_run = (start, last)
        if best_run is None:
            continue
        top, bottom = best_run
        length = bottom - top
        if not (_STEM_MIN * deg <= length <= _STEM_MAX * deg):
            continue
        candidates.append((float(x), top, bottom))

    # 相邻列合并成一根符干
    stems: list[tuple[float, int, int]] = []
    for x, top, bottom in candidates:
        if stems and x - stems[-1][0] <= 2:
            previous = stems[-1]
            stems[-1] = (
                (previous[0] + x) / 2,
                min(previous[1], top),
                max(previous[2], bottom),
            )
        else:
            stems.append((x, top, bottom))
    # 小节线：宽度很窄但高度占满谱表，且贴边
    margin = max(3.0, 0.4 * deg)
    return [
        stem for stem in stems
        if not (stem[0] < margin or stem[0] > width - margin)
        and (stem[2] - stem[1]) < _STEM_MAX * deg * 0.95
    ]


def _beam_count(dark: np.ndarray, left: tuple, right: tuple, deg: float) -> int:
    x0 = int(left[0]) + 2
    x1 = int(right[0]) - 2
    if x1 - x0 < max(4, deg * 0.5):
        return 0
    top = int(min(left[1], right[1]) - 0.6 * deg)
    bottom = int(max(left[1], right[1]) + 1.2 * deg)
    top = max(0, top)
    bottom = min(dark.shape[0], bottom)
    coverage = dark[top:bottom, x0:x1].mean(axis=1)
    rows = np.flatnonzero(coverage > _BEAM_COVERAGE)
    if len(rows) == 0:
        return 0
    groups = [[int(rows[0])]]
    for row in rows[1:]:
        if int(row) - groups[-1][-1] <= max(1, int(deg * 0.35)):
            groups[-1].append(int(row))
        else:
            groups.append([int(row)])
    return min(3, len(groups))


def _flag_count(dark: np.ndarray, stem: tuple, deg: float) -> int:
    x = int(stem[0]) + 1
    top = int(stem[1])
    right = min(dark.shape[1], x + int(2.2 * deg))
    bottom = min(dark.shape[0], top + int(1.8 * deg))
    if right <= x or bottom <= top:
        return 0
    region = dark[max(0, top) : bottom, x:right]
    if region.sum() < 0.12 * deg * deg:
        return 0
    rows = np.flatnonzero(region.mean(axis=1) > 0.15)
    if len(rows) == 0:
        return 0
    groups = 1
    for previous, row in zip(rows, rows[1:]):
        if int(row) - int(previous) > max(1, int(deg * 0.3)):
            groups += 1
    return min(2, groups)


def _has_dot(dark: np.ndarray, stem: tuple, deg: float, line_rows: list[int]) -> bool:
    y = int(stem[2]) - int(0.4 * deg)
    x0 = int(stem[0] + 0.6 * deg)
    x1 = min(dark.shape[1], int(stem[0] + 1.5 * deg))
    y0 = max(0, y - int(0.6 * deg))
    y1 = min(dark.shape[0], y + int(0.6 * deg))
    if x1 <= x0 or y1 <= y0:
        return False
    region = dark[y0:y1, x0:x1].copy()
    for row in line_rows:
        if y0 <= row < y1:
            region[row - y0, :] = False
    ink = int(region.sum())
    return 3 <= ink <= 0.45 * deg * deg


def read_measure_rhythm(
    arr: np.ndarray,
    system: System,
    measure_box: MeasureBox,
    deg: float,
    expected_ticks: int | None = None,
) -> list[BeatShape]:
    """一个小节的时值候选；`unknown` 表示这块交给模型。"""
    top = max(0, int(system.y0) - 3)
    bottom = min(arr.shape[0], int(system.y1) + 3)
    left = max(0, int(measure_box.x0))
    right = min(arr.shape[1], int(measure_box.x1))
    if bottom - top < 4 or right - left < 4:
        return []
    cut = adaptive_cut(arr)
    window = arr[top:bottom, left:right]
    # 不去掉五线谱的线：符干穿过谱线时墨迹是连续的，去掉反而把符干切成几段。
    dark = window < cut
    line_rows = [
        row + max(0, top - 2) - top
        for row in staff_lines(arr[max(0, top - 2) : min(arr.shape[0], bottom + 2)], frac=0.6)
    ]

    # 量连梁、符尾、附点时要把谱线行去掉（否则谱线本身会被当成横梁/墨迹）；
    # 量符干不能去，符干穿过谱线时是一条连续的竖线。
    beam_dark = dark.copy()
    for row in line_rows:
        beam_dark[max(0, row) : row + 1, :] = False

    stems = _stems(dark, deg, dark.shape[1])
    if not stems:
        # 多小节休止条：一条几乎贯穿全宽的粗横线
        coverage = beam_dark.mean(axis=1).max() if beam_dark.size else 0.0
        if coverage > 0.8:
            return [BeatShape(x=(left + right) / 2, duration="whole", kind="rest",
                              evidence={"detected": "multi-rest-bar", "coverage": float(coverage)})]
        ink = int(dark.sum())
        if ink < 0.6 * deg * deg:
            return [BeatShape(x=(left + right) / 2, duration="whole", kind="rest")]
        return [BeatShape(x=(left + right) / 2, duration="whole", kind="note",
                          evidence={"detected": "no-stem", "ink": ink})]

    stems.sort(key=lambda item: item[0])
    beams = {}
    for left_stem, right_stem in zip(stems, stems[1:]):
        gap = right_stem[0] - left_stem[0]
        if 0.5 * deg <= gap <= 4.5 * deg:
            count = _beam_count(beam_dark, left_stem, right_stem, deg)
            if count:
                beams[left_stem[0]] = max(beams.get(left_stem[0], 0), count)
                beams[right_stem[0]] = max(beams.get(right_stem[0], 0), count)

    shapes: list[BeatShape] = []
    for stem in stems:
        count = beams.get(stem[0], 0)
        if count == 0:
            flags = _flag_count(beam_dark, stem, deg)
            count = flags
        duration = {0: "quarter", 1: "eighth", 2: "16th", 3: "32nd"}.get(count, "unknown")
        dots = 1 if _has_dot(dark, stem, deg, line_rows) else 0
        shapes.append(
            BeatShape(
                x=stem[0] + left,
                duration=duration,
                dots=dots,
                evidence={"stem_top": stem[1], "stem_bottom": stem[2], "beams": count},
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
