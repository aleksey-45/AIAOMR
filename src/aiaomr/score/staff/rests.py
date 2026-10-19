"""休止符（`docs/spec-staff.md` SR-37..39b）。

三组按形状分：
- 全休止 / 二分休止：实心小矩形，**只靠挂线位置区分**——全休止挂在第四条线下方（矩形上沿贴线），
  二分休止坐在第三条线上（矩形下沿贴线）。用 `ctx.line_rows` 判，不按高度猜（SR-37）。
- 四分休止：折线字形（又高又窄），按形状比例判（SR-38）。
- 八、十六、三十二分休止：钩状字形，数左侧凸出的钩数 1/2/3（SR-39，和符尾同一套逻辑）。
- 多小节休止条：保留原判据（SR-39b）。

`Finding.value` 统一用 tick（1/32 拍为 1，四分 = 8），类别名写进 `evidence["category"]`。
"""

from __future__ import annotations

import numpy as np

from ...kernel.config import StaffConfig, load_staff_config
from .base import Criterion, Finding
from .context import GeoContext

# 休止类别 → tick（1/32 拍为 1）：纯语义映射表，不是阈值。
REST_TICKS = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2, "32nd": 1}
# 钩数 → 类别：纯语义映射表。
REST_BY_HOOKS = {1: "eighth", 2: "16th", 3: "32nd"}


def _merge_vertical(parts: list[list[int]], deg: float) -> list[list[int]]:
    """把被谱线切开的同一字形碎片按"x 重叠、上下间距小"合回一个框。"""
    merged = True
    while merged:
        merged = False
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                a, b = parts[i], parts[j]
                overlap = min(a[2], b[2]) - max(a[0], b[0])
                width = max(1, min(a[2] - a[0], b[2] - b[0]))
                gap = max(a[1], b[1]) - min(a[3], b[3])
                if overlap > 0.45 * width and gap <= 0.6 * deg:
                    parts[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    parts.pop(j)
                    merged = True
                    break
            if merged:
                break
    return parts


class RestBarCriterion(Criterion):
    """多小节休止条：一条几乎贯穿小节宽度的粗横线，没有符干。"""

    name = "rest_bar"

    def __init__(self, staff: StaffConfig | None = None) -> None:
        self.staff = staff if staff is not None else load_staff_config()

    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        if ctx.dark.size == 0:
            return []
        coverage = float(ctx.beam_dark.mean(axis=1).max())
        if coverage > self.staff.rest_bar_coverage:
            return [Finding(kind=self.name, value=float(REST_TICKS["whole"]),
                            bbox=(0, 0, ctx.width, ctx.height), evidence={"category": "rest_bar"})]
        return []


class RestRectCriterion(Criterion):
    """全休止 / 二分休止：实心小矩形，按贴的是哪条线分。"""

    name = "rest_rect"

    def __init__(self, staff: StaffConfig | None = None) -> None:
        self.staff = staff if staff is not None else load_staff_config()

    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        import cv2

        if ctx.dark.size == 0 or not ctx.line_rows:
            return []
        deg = ctx.deg
        mask = ctx.beam_dark.astype(np.uint8) * 255
        count, _labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        min_w, max_w = self.staff.rest_rect_w_deg
        min_h, max_h = self.staff.rest_rect_h_deg
        snap = self.staff.rest_line_snap_deg * deg
        out: list[Finding] = []
        for index in range(1, count):
            x, y, w, h, area = (int(value) for value in stats[index])
            if not (min_w * deg <= w <= max_w * deg and min_h * deg <= h <= max_h * deg):
                continue
            if area / float(w * h) < self.staff.rest_rect_fill_min:
                continue
            top_gap = min(abs(y - row) for row in ctx.line_rows)
            bottom_gap = min(abs(y + h - row) for row in ctx.line_rows)
            if top_gap <= snap and bottom_gap > snap:
                category = "whole"  # 上沿贴线：挂在第四条线下方
            elif bottom_gap <= snap and top_gap > snap:
                category = "half"  # 下沿贴线：坐在第三条线上
            else:
                continue
            out.append(
                Finding(
                    kind=self.name,
                    value=float(REST_TICKS[category]),
                    bbox=(float(x), float(y), float(x + w), float(y + h)),
                    evidence={
                        "category": f"rest_{category}",
                        "attach": "below_line" if category == "whole" else "on_line",
                        "line": int(min(ctx.line_rows, key=lambda row: abs((y if category == "whole" else y + h) - row))),
                        "fill": round(area / float(w * h), 3),
                    },
                )
            )
        return out


class RestGlyphCriterion(Criterion):
    """四分休止与八/十六/三十二分休止：折线形按比例，钩状形按钩数。"""

    name = "rest_glyph"

    def __init__(self, staff: StaffConfig | None = None) -> None:
        self.staff = staff if staff is not None else load_staff_config()

    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        import cv2

        if ctx.dark.size == 0:
            return []
        deg = ctx.deg
        min_h, max_h = self.staff.rest_glyph_h_deg
        mask = ctx.beam_dark.astype(np.uint8) * 255
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        parts: list[list[int]] = []
        for index in range(1, count):
            x, y, w, h, area = (int(value) for value in stats[index])
            if area < max(8.0, 0.02 * deg * deg):
                continue
            if x <= 0 or y <= 0 or x + w >= ctx.width or y + h >= ctx.height:
                continue
            if 0.3 * deg <= w <= 1.6 * deg and 0.3 * deg <= h:
                parts.append([x, y, x + w, y + h])
        out: list[Finding] = []
        for x0, y0, x1, y1 in _merge_vertical(parts, deg):
            width, height = x1 - x0, y1 - y0
            if not (min_h * deg <= height <= max_h * deg and 0.4 * deg <= width <= 1.7 * deg):
                continue
            category = self._category(ctx, x0, y0, x1, y1)
            if category is None:
                continue
            out.append(
                Finding(
                    kind=self.name,
                    value=float(REST_TICKS[category]),
                    bbox=(float(x0), float(y0), float(x1), float(y1)),
                    evidence={"category": f"rest_{category}", "h_deg": round(height / deg, 2)},
                )
            )
        return out

    def _category(self, ctx: GeoContext, x0: int, y0: int, x1: int, y1: int) -> str | None:
        width, height = x1 - x0, y1 - y0
        if height / max(1, width) >= self.staff.rest_quarter_aspect:
            return "quarter"
        hooks = _count_hooks(ctx.beam_dark[y0:y1, x0:x1], self.staff.rest_hook_protrude_deg)
        return REST_BY_HOOKS.get(hooks)


def _count_hooks(glyph: np.ndarray, protrude: float) -> int:
    """数钩数：字形逐行最左墨迹相对主体左缘向左凸出的连续行段数。

    八分休止是"7"（顶部一个球 = 1 个钩），十六分 / 三十二分在左侧再多一到两个钩。
    `protrude` 是"凸出多少（相对字形宽）才算一个钩"，来自 `cfg.staff.rest_hook_protrude_deg`。
    """
    if glyph.size == 0:
        return 0
    rows = np.flatnonzero(glyph.any(axis=1))
    if rows.size == 0:
        return 0
    leftmost = []
    for row in rows:
        columns = np.flatnonzero(glyph[row])
        if columns.size:
            leftmost.append(int(columns[0]))
    if not leftmost:
        return 0
    width = glyph.shape[1]
    body = int(np.median(leftmost))
    threshold = body - protrude * width
    groups = 0
    inside = False
    for value in leftmost:
        protrudes = value <= threshold
        if protrudes and not inside:
            groups += 1
        inside = protrudes
    return groups
