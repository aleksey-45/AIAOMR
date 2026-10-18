"""休止符（`docs/spec-staff.md` SR-37..39b）。

任务 0 只有"多小节休止条"这一条判据；全休止、二分休止、四分休止、八分休止的
三组判据是任务 2 的事（`rests.py` 就是它们的归属文件）。
"""

from __future__ import annotations

from .base import Criterion, Finding
from .context import GeoContext

# 多小节休止条的横向覆盖率下限。
REST_BAR_COVERAGE = 0.8


class RestBarCriterion(Criterion):
    """多小节休止条：一条几乎贯穿小节宽度的粗横线，没有符干。"""

    name = "rest_bar"

    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        if ctx.dark.size == 0:
            return []
        coverage = float(ctx.beam_dark.mean(axis=1).max())
        if coverage > REST_BAR_COVERAGE:
            return [Finding(kind=self.name, value=coverage, bbox=(0, 0, ctx.width, ctx.height))]
        return []
