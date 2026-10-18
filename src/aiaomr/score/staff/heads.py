"""符头判据（`docs/spec-staff.md` SR-20..24）。

任务 0 沿用原型：抹符干列后找连通域，再在原始墨迹上数内洞判"实心/空心"。
任务 2 要按规范补齐：填充率与环宽做主判据、`templates.py` 的 NCC 复核、
洞判据降级为佐证（真图上谱线穿过符头内部会把洞切成两半）。
"""

from __future__ import annotations

from .base import Criterion, Finding
from .context import GeoContext


class HeadCriterion(Criterion):
    """符头：`value` 1.0 = 空心，0.0 = 实心，外接框是窗口坐标。"""

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
