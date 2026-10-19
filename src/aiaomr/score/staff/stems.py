"""符干预判据（`docs/spec-staff.md` SR-25..27）。

符干是竖直墨迹，长度 `cfg.staff.stem_len_deg`（2.0–5.5 倍 deg），穿过谱线时中间是连续的；
长度超上限通常是相邻谱线的竖线或小节线误检，丢弃。
"""

from __future__ import annotations

from ...kernel.config import StaffConfig, load_staff_config
from .base import Criterion, Finding
from .context import GeoContext


class StemCriterion(Criterion):
    """符干候选：每根符干给出一个 `Finding`，`value` 是它的 x。"""

    name = "stem"

    def __init__(self, staff: StaffConfig | None = None) -> None:
        self.staff = staff if staff is not None else load_staff_config()

    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        min_len, max_len = (bound * ctx.deg for bound in self.staff.stem_len_deg)
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
            if min_len <= bottom - top <= max_len:
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
            and (stem[2] - stem[1]) < max_len * 0.95
        ]
        return [
            Finding(kind=self.name, value=float(x), bbox=(x, float(top), x, float(bottom)))
            for x, top, bottom in kept
        ]
