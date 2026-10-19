"""附点与断音点（`docs/spec-staff.md` SR-33..36）。

附点锚在**符头右侧**（符头中心偏右 `dot_offset_deg`，纵向 ±`dot_dy_deg`），不再锚在符干底部
（符干朝下时会偏，SR-33）。支持双附点（第二点在更右边，SR-34）；断音点画在符头另一侧，
由于只认"中心右侧"的小墨点，自然被排除（SR-35）。休止符的附点同样按这条判，锚点是休止字形
右侧，`evidence["anchor"]` 写明是 `head` 还是 `rest`（SR-36）。

锚点来源：调用方给的 `findings["head"]` / `findings["rest_*"]`；没给就在本窗口内自己跑一遍
符头/休止判据（读谱编排层是任务 3/4 才接线，先保住单判据可用）。
"""

from __future__ import annotations

import numpy as np

from ...kernel.config import StaffConfig, load_staff_config
from .base import Criterion, Finding
from .context import GeoContext

# 第二个附点相对第一个附点的额外位移，deg（双附点）。
DOT_SECOND_GAP_DEG = 0.9
# 附点自身外接框的上限，deg（比这个大的不是点）。
DOT_MAX_SIDE_DEG = 0.5


class DotCriterion(Criterion):
    """附点：`value` = 锚点上的附点个数（1 或 2），`bbox` 是第一个附点。"""

    name = "dot"

    def __init__(self, staff: StaffConfig | None = None) -> None:
        self.staff = staff if staff is not None else load_staff_config()

    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        if ctx.dark.size == 0:
            return []
        findings = findings or {}
        anchors = self._anchors(ctx, findings)
        if not anchors:
            return []
        blobs = self._dot_blobs(ctx)
        if not blobs:
            return []
        deg = ctx.deg
        near, far = (value * deg for value in self.staff.dot_offset_deg)
        dy_max = self.staff.dot_dy_deg * deg
        out: list[Finding] = []
        for anchor_bbox, anchor_kind in anchors:
            center_x = (anchor_bbox[0] + anchor_bbox[2]) / 2
            center_y = (anchor_bbox[1] + anchor_bbox[3]) / 2
            chosen = []
            for blob in blobs:
                blob_x = (blob[0] + blob[2]) / 2
                blob_y = (blob[1] + blob[3]) / 2
                dx = blob_x - center_x
                dy = blob_y - center_y
                if not (near <= dx <= far + DOT_SECOND_GAP_DEG * deg):
                    continue  # 左侧/太远的小点不是这个符头的附点（断音点也在这里被排除）
                if abs(dy) > dy_max:
                    continue
                chosen.append((dx, blob))
            if not chosen:
                continue
            chosen.sort(key=lambda item: item[0])
            for order, (dx, blob) in enumerate(chosen):
                out.append(
                    Finding(
                        kind=self.name,
                        value=float(len(chosen)),
                        bbox=(float(blob[0]), float(blob[1]), float(blob[2]), float(blob[3])),
                        evidence={
                            "anchor": anchor_kind,
                            "anchor_bbox": [round(float(value), 1) for value in anchor_bbox],
                            "dx_deg": round(dx / deg, 2),
                            "index": order + 1,
                            "dots": len(chosen),
                        },
                    )
                )
        return out

    # ------------------------------------------------------------ 锚点
    def _anchors(self, ctx: GeoContext, findings: dict) -> list[tuple[tuple, str]]:
        heads = findings.get("head")
        if heads is None:
            from .heads import HeadCriterion

            heads = HeadCriterion(self.staff).detect(ctx, findings)
        anchors: list[tuple[tuple, str]] = [(finding.bbox, "head") for finding in heads]

        rest_findings: list[Finding] = []
        for key in ("rest_rect", "rest_glyph"):
            rest_findings.extend(findings.get(key, []))
        if not rest_findings:
            from .rests import RestGlyphCriterion, RestRectCriterion

            rest_findings.extend(RestRectCriterion(self.staff).detect(ctx, findings))
            rest_findings.extend(RestGlyphCriterion(self.staff).detect(ctx, findings))
        anchors.extend((finding.bbox, "rest") for finding in rest_findings)
        return anchors

    # ------------------------------------------------------------ 小墨点
    def _dot_blobs(self, ctx: GeoContext) -> list[tuple[int, int, int, int]]:
        import cv2

        deg = ctx.deg
        min_area = self.staff.dot_min_area_px
        max_area = self.staff.dot_max_area_deg2 * deg * deg
        max_side = DOT_MAX_SIDE_DEG * deg
        mask = ctx.beam_dark.astype(np.uint8) * 255
        count, _labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        blobs: list[tuple[int, int, int, int]] = []
        for index in range(1, count):
            x, y, w, h, area = (int(value) for value in stats[index])
            if not (min_area <= area <= max_area):
                continue
            if w < 2 or h < 2 or w > max_side or h > max_side:
                continue
            if not 0.5 <= w / float(h) <= 2.0:
                continue
            blobs.append((x, y, x + w, y + h))
        return blobs
