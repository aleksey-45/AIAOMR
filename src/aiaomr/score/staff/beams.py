"""横梁段与符尾（`docs/spec-staff.md` SR-28..32、SR-41..43）。

任务 3 起，`BeamCriterion` 输出的是**横梁段**而不是"两干之间有几行"：每条横梁段有自己的
左右端点（`bbox` 的 x0/x1）和它接在哪两根符干上（`evidence.attachLeft/attachRight`）。
归属层（`group.py`）用这些段建图：连通块 = 连梁组，每根符干的横梁条数 = **入射段条数**，
组内顺序由"只有右段 / 只有左段 / 两侧都有"判定。

这一条很关键：前八后十六这种混合时值，二级横梁只从第二个音符开始，按"两干之间的行数"会
把第一个音符也算成十六分；按入射段数才对。
"""

from __future__ import annotations

import numpy as np

from ...kernel.config import StaffConfig, load_staff_config
from .base import Criterion, Finding
from .context import GeoContext


class BeamCriterion(Criterion):
    """横梁段：`value` 是层号（1 = 最靠符干端的那条），`bbox` 是这一段的左右与上下范围。"""

    name = "beam"

    def __init__(self, staff: StaffConfig | None = None) -> None:
        self.staff = staff if staff is not None else load_staff_config()

    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        stems = (findings or {}).get("stem", [])
        min_gap, max_gap = self.staff.beam_gap_deg
        tol = self.staff.beam_attach_tol_deg * ctx.deg
        out: list[Finding] = []
        for left, right in zip(stems, stems[1:]):
            gap = right.value - left.value
            if not (min_gap * ctx.deg <= gap <= max_gap * ctx.deg):
                continue
            out.extend(self._segments(ctx, left, right, tol))
        return out

    def _segments(self, ctx: GeoContext, left: Finding, right: Finding, tol: float) -> list[Finding]:
        x0 = int(left.value) + 2
        x1 = int(right.value) - 2
        if x1 - x0 < max(4, ctx.deg * 0.5):
            return []
        top = max(0, int(min(left.bbox[1], right.bbox[1]) - 0.6 * ctx.deg))
        bottom = min(ctx.height, int(max(left.bbox[1], right.bbox[1]) + 1.2 * ctx.deg))
        region = ctx.beam_dark[top:bottom, x0:x1]
        if region.size == 0:
            return []
        coverage = region.mean(axis=1)
        rows = np.flatnonzero(coverage > self.staff.beam_coverage)
        if len(rows) == 0:
            return []

        # 行分组 = 分层：层间空隙比层厚小，用 beam_layer_gap_deg 控制
        gap = max(1, int(ctx.deg * self.staff.beam_row_gap_deg))
        layers: list[list[int]] = [[int(rows[0])]]
        for row in rows[1:]:
            if int(row) - layers[-1][-1] <= gap:
                layers[-1].append(int(row))
            else:
                layers.append([int(row)])

        segments: list[Finding] = []
        for layer_index, layer in enumerate(layers[:3], start=1):
            band = region[layer[0] : layer[-1] + 1, :]
            columns = np.flatnonzero(band.any(axis=0))
            if columns.size == 0:
                continue
            start = x0 + int(columns[0])
            end = x0 + int(columns[-1]) + 1
            attach_left = start <= left.value + tol
            attach_right = end >= right.value - tol
            if not attach_left and not attach_right:
                continue  # 段两头都接不上符干：不是连梁（横梁残留、休止条之类）
            segments.append(
                Finding(
                    kind=self.name,
                    value=float(layer_index),
                    bbox=(float(start), float(top + layer[0]), float(end), float(top + layer[-1] + 1)),
                    evidence={
                        "left": left.value,
                        "right": right.value,
                        "attachLeft": bool(attach_left),
                        "attachRight": bool(attach_right),
                        "layer": layer_index,
                    },
                )
            )
        return segments


class FlagCriterion(Criterion):
    """符尾：没有连梁时，符干顶端右侧的小钩；1/2 个对应八分/十六分。"""

    name = "flag"

    def __init__(self, staff: StaffConfig | None = None) -> None:
        self.staff = staff if staff is not None else load_staff_config()

    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        stems = (findings or {}).get("stem", [])
        min_ink = self.staff.flag_min_ink_deg2 * ctx.deg * ctx.deg
        row_gap = max(1, int(ctx.deg * self.staff.flag_row_gap_deg))
        out: list[Finding] = []
        for stem in stems:
            x = int(stem.value) + 1
            top = int(stem.bbox[1])
            right = min(ctx.width, x + int(2.2 * ctx.deg))
            bottom = min(ctx.height, top + int(1.8 * ctx.deg))
            if right <= x or bottom <= top:
                continue
            region = ctx.beam_dark[max(0, top) : bottom, x:right].copy()
            # 符干本身就在这块区域里：不先把它抹掉，符干自己的墨迹就会被当成"符尾"，
            # 每个四分音符都会被判成八分。
            region[:, : 2] = False
            if region.sum() < min_ink:
                continue
            rows = np.flatnonzero(region.mean(axis=1) > self.staff.flag_row_mean)
            groups = 1
            for previous, row in zip(rows, rows[1:]):
                if int(row) - int(previous) > row_gap:
                    groups += 1
            out.append(
                Finding(
                    kind=self.name,
                    value=float(min(2, groups)),
                    bbox=(x, top, right, bottom),
                    evidence={"stem": stem.value},
                )
            )
        return out
