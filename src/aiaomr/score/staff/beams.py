"""横梁段与符尾（`docs/spec-staff.md` SR-28..32）。

任务 0 仍按"相邻符干之间数行数"的老口径实现，左右延伸建图与入射段计数是任务 3 的事：
那部分是归属问题（`group.py`），不是判据问题。阈值一律以 deg 为单位（R-03）。
"""

from __future__ import annotations

import numpy as np

from .base import Criterion, Finding
from .context import GeoContext

BEAM_COVERAGE = 0.85
FLAG_MIN_INK = 0.12
FLAG_ROW_MEAN = 0.15


class BeamCriterion(Criterion):
    """连梁：两根符干顶部之间的粗横线，行组数 1/2/3 对应八/十六/三十二分。

    注意：这里只数"这两根符干之间有几条横线"，不判断谁和谁同组、谁是组内最后一个；
    那是任务 3 的 `group.py` 用左右延伸建图去做的事。
    """

    name = "beam"

    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        stems = (findings or {}).get("stem", [])
        out: list[Finding] = []
        for left, right in zip(stems, stems[1:]):
            gap = right.value - left.value
            if not (0.5 * ctx.deg <= gap <= 4.5 * ctx.deg):
                continue
            count = self._count(ctx, left, right)
            if count:
                out.append(
                    Finding(
                        kind=self.name,
                        value=float(count),
                        bbox=(left.value, left.bbox[1], right.value, right.bbox[1]),
                        evidence={"left": left.value, "right": right.value},
                    )
                )
        return out

    def _count(self, ctx: GeoContext, left: Finding, right: Finding) -> int:
        x0 = int(left.value) + 2
        x1 = int(right.value) - 2
        if x1 - x0 < max(4, ctx.deg * 0.5):
            return 0
        top = max(0, int(min(left.bbox[1], right.bbox[1]) - 0.6 * ctx.deg))
        bottom = min(ctx.height, int(max(left.bbox[1], right.bbox[1]) + 1.2 * ctx.deg))
        coverage = ctx.beam_dark[top:bottom, x0:x1].mean(axis=1)
        rows = np.flatnonzero(coverage > BEAM_COVERAGE)
        if len(rows) == 0:
            return 0
        groups = [[int(rows[0])]]
        for row in rows[1:]:
            if int(row) - groups[-1][-1] <= max(1, int(ctx.deg * 0.35)):
                groups[-1].append(int(row))
            else:
                groups.append([int(row)])
        return min(3, len(groups))


class FlagCriterion(Criterion):
    """符尾：没有连梁时，符干顶端右侧的小钩；1/2 个对应八分/十六分。"""

    name = "flag"

    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        stems = (findings or {}).get("stem", [])
        out: list[Finding] = []
        for stem in stems:
            x = int(stem.value) + 1
            top = int(stem.bbox[1])
            right = min(ctx.width, x + int(2.2 * ctx.deg))
            bottom = min(ctx.height, top + int(1.8 * ctx.deg))
            if right <= x or bottom <= top:
                continue
            region = ctx.beam_dark[max(0, top) : bottom, x:right]
            if region.sum() < FLAG_MIN_INK * ctx.deg * ctx.deg:
                continue
            rows = np.flatnonzero(region.mean(axis=1) > FLAG_ROW_MEAN)
            groups = 1
            for previous, row in zip(rows, rows[1:]):
                if int(row) - int(previous) > max(1, int(ctx.deg * 0.3)):
                    groups += 1
            out.append(
                Finding(
                    kind=self.name,
                    value=float(min(2, groups)),
                    bbox=(x, top, right, bottom),
                )
            )
        return out
