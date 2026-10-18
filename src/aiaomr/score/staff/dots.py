"""附点与断音点（`docs/spec-staff.md` SR-33..36）。

附点挂在**符头右侧**，不挂符干底部（符干朝下时按符干底部会偏）。
断音点画在符头另一侧，不算时值，判据必须排除相反侧的小墨点。
"""

from __future__ import annotations

import numpy as np

from .base import Criterion, Finding
from .context import GeoContext

# 附点的面积范围：绝对下限（抗噪）与 deg² 上限（挡掉整行墨迹）。
DOT_MIN_INK = 3
DOT_MAX_INK = 0.45


class DotCriterion(Criterion):
    """附点：符头右下方的小墨点；`value` 恒为 1，位置在 `bbox` 里。"""

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
