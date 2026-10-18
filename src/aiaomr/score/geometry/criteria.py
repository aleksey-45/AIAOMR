"""几何判据：每一条"这是什么"都写成可单测的判据，阈值一律以 deg 为单位（R-03）。

判据只读 `GeoContext`，返回 `Finding`（种类、值、外接框、证据）。节奏装配在
`locate/rhythm.py` 里做：判据管"有没有、几个"，装配管"这几个数怎么变成一拍"。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .context import GeoContext

# 符干
STEM_MIN_DEG = 2.0
STEM_MAX_DEG = 5.5
# 连梁
BEAM_COVERAGE = 0.85
# 附点、符尾的墨迹下限（deg²）
DOT_MIN_INK = 3
DOT_MAX_INK = 0.45


@dataclass
class Finding:
    """一条几何判据的结论。`value` 的含义由 `kind` 决定。"""

    kind: str
    value: float
    bbox: tuple[float, float, float, float]
    evidence: dict = field(default_factory=dict)


class Criterion:
    """判据的公共接口；新增判据只要实现 `detect`。"""

    name = "criterion"

    def detect(self, ctx: GeoContext, findings: dict[str, list[Finding]] | None = None) -> list[Finding]:
        raise NotImplementedError


class StemCriterion(Criterion):
    """符干：竖直墨迹，长度 2.0–5.5 倍 deg，穿过谱线时中间是连续的。"""

    name = "stem"

    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        dark, deg, width = ctx.dark, ctx.deg, ctx.width
        if dark.size == 0:
            return []
        candidates: list[tuple[float, int, int]] = []
        for x in range(width):
            column = dark[:, x]
            best = None
            start = last = None
            for y in range(ctx.height):
                if column[y]:
                    if start is None:
                        start = last = y
                    elif y - last <= 3:
                        last = y
                    else:
                        if best is None or last - start > best[1] - best[0]:
                            best = (start, last)
                        start = last = y
                elif start is not None and y - last > 3:
                    if best is None or last - start > best[1] - best[0]:
                        best = (start, last)
                    start = None
            if start is not None and (best is None or last - start > best[1] - best[0]):
                best = (start, last)
            if best is None:
                continue
            top, bottom = best
            if STEM_MIN_DEG * deg <= bottom - top <= STEM_MAX_DEG * deg:
                candidates.append((float(x), top, bottom))

        stems: list[tuple[float, int, int]] = []
        for x, top, bottom in candidates:
            if stems and x - stems[-1][0] <= 2:
                previous = stems[-1]
                stems[-1] = ((previous[0] + x) / 2, min(previous[1], top), max(previous[2], bottom))
            else:
                stems.append((x, top, bottom))

        margin = max(3.0, 0.4 * deg)
        kept = [
            stem for stem in stems
            if not (stem[0] < margin or stem[0] > width - margin)
            and (stem[2] - stem[1]) < STEM_MAX_DEG * deg * 0.95
        ]
        return [
            Finding(kind=self.name, value=float(x), bbox=(x, float(top), x, float(bottom)))
            for x, top, bottom in kept
        ]


class BeamCriterion(Criterion):
    """连梁：两根符干顶部之间的粗横线，1/2/3 条分别对应八/十六/三十二分。"""

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
            if region.sum() < 0.12 * ctx.deg * ctx.deg:
                continue
            rows = np.flatnonzero(region.mean(axis=1) > 0.15)
            groups = 1
            for previous, row in zip(rows, rows[1:]):
                if int(row) - int(previous) > max(1, int(ctx.deg * 0.3)):
                    groups += 1
            out.append(Finding(kind=self.name, value=float(min(2, groups)), bbox=(x, top, right, bottom)))
        return out


class DotCriterion(Criterion):
    """附点：符头右下方的孤立小墨点；谱线行要先跳过，否则整条线都算墨迹。"""

    name = "dot"

    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        stems = (findings or {}).get("stem", [])
        out: list[Finding] = []
        for stem in stems:
            y = int(stem.bbox[3]) - int(0.4 * ctx.deg)
            x0 = int(stem.value + 0.6 * ctx.deg)
            x1 = min(ctx.width, int(stem.value + 1.5 * ctx.deg))
            y0 = max(0, y - int(0.6 * ctx.deg))
            y1 = min(ctx.height, y + int(0.6 * ctx.deg))
            if x1 <= x0 or y1 <= y0:
                continue
            region = ctx.beam_dark[y0:y1, x0:x1]
            ink = int(region.sum())
            if DOT_MIN_INK <= ink <= DOT_MAX_INK * ctx.deg * ctx.deg:
                out.append(Finding(kind=self.name, value=1.0, bbox=(x0, y0, x1, y1)))
        return out


class HeadCriterion(Criterion):
    """符头：把符干那几列抹掉后找连通域；"实心还是空心"看原始墨迹里有没有内洞。

    空心符头（二分/全音符）是一个闭合的圈，内洞在原始图里仍然闭合——符干是从外面
    贴上来的，不会把洞打开，所以洞要在 `dark` 上判，不能在抹过符干的掩码上判。
    """

    name = "head"

    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        import cv2

        if ctx.dark.size == 0:
            return []
        stems = (findings or {}).get("stem", [])
        mask = ctx.beam_dark.copy()
        for stem in stems:
            x = int(round(stem.value))
            top = max(0, int(stem.bbox[1]) - 1)
            bottom = min(ctx.height, int(stem.bbox[3]) + 2)
            mask[top:bottom, max(0, x - 1) : x + 2] = False

        binary = mask.astype("uint8") * 255
        count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        heads: list[Finding] = []
        min_w, max_w = 0.7 * ctx.deg, 1.9 * ctx.deg
        min_h, max_h = 0.3 * ctx.deg, 1.2 * ctx.deg
        for index in range(1, count):
            x, y, w, h, area = (int(v) for v in stats[index])
            if not (min_w <= w <= max_w and min_h <= h <= max_h):
                continue
            if w / max(1, h) < 1.1 or area < 0.15 * ctx.deg * ctx.deg:
                continue
            # 洞在原始墨迹上判；裁剪要给一圈余量，否则符干把圈切在裁剪边界上，洞就漏了
            pad = int(0.4 * ctx.deg)
            y0, y1 = max(0, y - pad), min(ctx.height, y + h + pad)
            x0, x1 = max(0, x - pad), min(ctx.width, x + w + pad)
            crop = (ctx.dark[y0:y1, x0:x1]).astype("uint8") * 255
            contours, hierarchy = cv2.findContours(crop, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            holes = 0
            if hierarchy is not None:
                for position, node in enumerate(hierarchy[0]):
                    if node[3] != -1 and cv2.contourArea(contours[position]) > 2:
                        holes += 1
            heads.append(
                Finding(
                    kind=self.name,
                    value=1.0 if holes else 0.0,
                    bbox=(float(x), float(y), float(x + w), float(y + h)),
                    evidence={"filled": holes == 0, "holes": holes, "area": area},
                )
            )
        return heads


class RestBarCriterion(Criterion):
    """多小节休止条：一条几乎贯穿小节宽度的粗横线，没有符干。"""

    name = "rest_bar"

    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        if ctx.dark.size == 0:
            return []
        coverage = float(ctx.beam_dark.mean(axis=1).max())
        if coverage > 0.8:
            return [Finding(kind=self.name, value=coverage, bbox=(0, 0, ctx.width, ctx.height))]
        return []


CRITERIA: list[Criterion] = [
    HeadCriterion(),
    StemCriterion(),
    BeamCriterion(),
    FlagCriterion(),
    DotCriterion(),
    RestBarCriterion(),
]
