"""符头判据（`docs/spec-staff.md` SR-20..24）。

真图上两条实现决定（任务 2 按 28 个真图样本实测后定的，理由见报告）：

1. **候选分两条支路拿**。SR-20 的字面做法是"抹谱线、抹符干列后的连通域"，但真图上谱线会把
   空心符头的环切成几段弧，按 0.7–1.9·deg 的宽度过滤后基本拿不到完整的空心符头。所以：
   - 实心符头：在 `ctx.dark` 上做腐蚀，细笔画（谱线 2~3px、符干 3~4px、横梁 9~10px）被
     `head_erode_deg` 腐蚀掉，实心符头留下一个核；核按腐蚀核大小膨胀回去就是候选框。
   - 空心符头：找被墨迹围住的空腔（4 连通背景），合并被谱线切开的两个空腔；四周环壁必须
     薄（≤ `head_ring_max_deg`），空腔尺寸要落在符头孔的范围里。
2. **填充率是主判**：谱线行既不算墨也不算外接框面积；填充率与支路结论矛盾时，才用本窗口
   自举的两类模板做 NCC 复核（`templates.py`）。两套都不确定 → 不产出 Finding，编排层按
   AR-02 abstain。洞判据只作佐证写进 evidence，不推翻结论（SR-23）。
"""

from __future__ import annotations

import cv2
import numpy as np

from ...kernel.config import StaffConfig, load_staff_config
from .base import Criterion, Finding
from .context import GeoContext
from .templates import HeadTemplates

EMPTY = np.zeros((0, 0))


class HeadCriterion(Criterion):
    """符头：`value` 1.0 = 空心，0.0 = 实心，外接框是窗口坐标。"""

    name = "head"

    def __init__(self, staff: StaffConfig | None = None) -> None:
        self.staff = staff if staff is not None else load_staff_config()

    # ------------------------------------------------------------------ 入口
    def detect(self, ctx: GeoContext, findings=None) -> list[Finding]:
        if ctx.dark.size == 0:
            return []
        candidates = self._filled_candidates(ctx) + self._hollow_candidates(ctx)
        candidates = self._drop_conflicts(candidates)
        if not candidates:
            return []
        templates = HeadTemplates.bootstrap(
            {
                label: [self._patch(ctx, cand["bbox"]) for cand in candidates if cand["label"] == label]
                for label in ("hollow", "filled")
            },
            self.staff.template_norm_w,
            self.staff.template_norm_h,
        )
        results: list[Finding] = []
        for cand in candidates:
            verdict = self._classify(ctx, cand, templates)
            if verdict is None:
                continue
            label, evidence = verdict
            results.append(
                Finding(
                    kind=self.name,
                    value=1.0 if label == "hollow" else 0.0,
                    bbox=cand["bbox"],
                    evidence=evidence,
                )
            )
        results.sort(key=lambda finding: finding.bbox[0])
        return results

    # ------------------------------------------------------------ 候选（实心）
    def _filled_candidates(self, ctx: GeoContext) -> list[dict]:
        deg = ctx.deg
        kernel_size = max(3, int(round(self.staff.head_erode_deg * deg)))
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        eroded = cv2.erode(ctx.dark.astype(np.uint8), kernel)
        count, _labels, stats, _ = cv2.connectedComponentsWithStats(eroded, connectivity=8)
        min_side = max(2, int(round(0.08 * deg)))
        out: list[dict] = []
        for index in range(1, count):
            x, y, w, h, _area = (int(value) for value in stats[index])
            if w < min_side or h < min_side:
                continue
            # 腐蚀核按核大小膨胀回去才是符头外接框；膨胀量取核半径（腐蚀吃掉的就是这么多）。
            shift = max(1, kernel_size // 2)
            x0, y0 = x - shift, y - shift
            x1, y1 = x + w + shift, y + h + shift
            if not self._box_ok(ctx, x0, y0, x1, y1):
                continue
            out.append({"label": "filled", "bbox": (float(x0), float(y0), float(x1), float(y1)),
                        "source": "erode_core"})
        return out

    # ------------------------------------------------------------ 候选（空心）
    def _hollow_candidates(self, ctx: GeoContext) -> list[dict]:
        """空腔 → 每个空腔按自己的四周环壁扩成候选框 → 合并被谱线切开的上下两半。"""
        deg = ctx.deg
        background = (~ctx.dark).astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(background, connectivity=4)
        edge = set(labels[0]) | set(labels[-1]) | set(labels[:, 0]) | set(labels[:, -1])
        boxes: list[list[int]] = []
        rings: dict[tuple[int, int, int, int], float] = {}
        for index in range(1, count):
            if index in edge:
                continue
            x, y, w, h, _area = (int(value) for value in stats[index])
            if h < self.staff.head_cavity_min_h_deg * deg or w < 2 or h < 2:
                continue
            if w / h > self.staff.head_cavity_aspect_max:
                continue
            walls = self._wall_thickness(ctx, x, y, x + w, y + h)
            if walls is None or max(walls) > self.staff.head_ring_max_deg * deg:
                continue
            left, right, top, bottom = walls
            box = [x - left, y - top, x + w + right, y + h + bottom]
            boxes.append(box)
            rings[tuple(box)] = float(
                ((x + w + right) - (x - left) - w + (y + h + bottom) - (y - top) - h) / 4 / deg
            )
        boxes = self._merge_cavities(boxes, deg)
        out: list[dict] = []
        for x0, y0, x1, y1 in boxes:
            if not self._box_ok(ctx, x0, y0, x1, y1):
                continue
            ring = rings.get((x0, y0, x1, y1))
            if ring is None:
                ring = min(x1 - x0, y1 - y0) / 4 / deg
            out.append({"label": "hollow", "bbox": (float(x0), float(y0), float(x1), float(y1)),
                        "source": "cavity", "ring": float(ring)})
        return out

    @staticmethod
    def _merge_cavities(cavities: list[list[int]], deg: float) -> list[list[int]]:
        """一个空腔被谱线切成上下两半时合回一个：x 重叠、上下间距 ≤ 0.6·deg。"""
        merged = True
        while merged:
            merged = False
            for i in range(len(cavities)):
                for j in range(i + 1, len(cavities)):
                    a, b = cavities[i], cavities[j]
                    overlap = min(a[2], b[2]) - max(a[0], b[0])
                    width = max(1, min(a[2] - a[0], b[2] - b[0]))
                    gap = max(a[1], b[1]) - min(a[3], b[3])
                    if overlap > 0.5 * width and gap <= 0.6 * deg:
                        cavities[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                        cavities.pop(j)
                        merged = True
                        break
                if merged:
                    break
        return cavities

    @staticmethod
    def _wall_thickness(ctx: GeoContext, x0: int, y0: int, x1: int, y1: int):
        """量空腔四周环壁的厚度（像素）。在空腔自己的中列/中行上向外量，跳过谱线行。"""
        dark = ctx.dark
        line_rows = set(ctx.line_rows)
        rows = [row for row in range(max(0, y0), min(ctx.height, y1)) if row not in line_rows]
        if not rows:
            return None
        row = rows[len(rows) // 2]

        def run(x: int, y: int, dx: int, dy: int) -> int:
            steps = 0
            while 0 <= x < ctx.width and 0 <= y < ctx.height and dark[y, x]:
                steps += 1
                x += dx
                y += dy
            return steps

        left = run(x0 - 1, row, -1, 0)
        right = run(x1, row, 1, 0)
        middle = (x0 + x1) // 2
        top = run(middle, y0 - 1, 0, -1)
        bottom = run(middle, y1, 0, 1)
        if min(left, right, top, bottom) < 1:
            return None
        return left, right, top, bottom

    # ------------------------------------------------------------ 框与分类
    def _box_ok(self, ctx: GeoContext, x0: float, y0: float, x1: float, y1: float) -> bool:
        deg = ctx.deg
        if x0 < 1 or y0 < 1 or x1 > ctx.width - 1 or y1 > ctx.height - 1:
            return False
        width, height = x1 - x0, y1 - y0
        min_w, max_w = self.staff.head_w_deg
        min_h, max_h = self.staff.head_h_deg
        if not (min_w * deg <= width <= max_w * deg and min_h * deg <= height <= max_h * deg):
            return False
        return width / max(1.0, height) >= self.staff.head_aspect_min

    def _patch(self, ctx: GeoContext, bbox) -> np.ndarray:
        x0, y0, x1, y1 = (int(round(value)) for value in bbox)
        region = ctx.beam_dark[max(0, y0):y1, max(0, x0):x1]
        if region.size == 0:
            return EMPTY
        return region.astype(np.uint8) * 255

    def _fill_ratio(self, ctx: GeoContext, bbox) -> float:
        """填充率：谱线行既不算墨也不计入外接框面积（真图上谱线会横穿符头）。"""
        x0, y0, x1, y1 = (int(round(value)) for value in bbox)
        width, height = x1 - x0, y1 - y0
        if width <= 0 or height <= 0:
            return 0.0
        line_rows = [row for row in ctx.line_rows if y0 <= row < y1]
        line_ink = sum(int(ctx.dark[row, x0:x1].sum()) for row in line_rows)
        ink = int(ctx.dark[y0:y1, x0:x1].sum()) - line_ink
        area = width * height - len(line_rows) * width
        return ink / area if area > 0 else 0.0

    def _hole_count(self, ctx: GeoContext, bbox) -> int:
        """洞判据：只作佐证（SR-23）。在原始墨迹上数内洞。"""
        x0, y0, x1, y1 = (int(round(value)) for value in bbox)
        pad = int(round(0.3 * ctx.deg))
        cy0, cy1 = max(0, y0 - pad), min(ctx.height, y1 + pad)
        cx0, cx1 = max(0, x0 - pad), min(ctx.width, x1 + pad)
        crop = (ctx.dark[cy0:cy1, cx0:cx1]).astype(np.uint8) * 255
        contours, hierarchy = cv2.findContours(crop, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        holes = 0
        if hierarchy is not None:
            for position, node in enumerate(hierarchy[0]):
                if node[3] != -1 and cv2.contourArea(contours[position]) > 2:
                    holes += 1
        return holes

    def _classify(self, ctx: GeoContext, cand: dict, templates) -> tuple[str, dict] | None:
        bbox = cand["bbox"]
        fill = self._fill_ratio(ctx, bbox)
        evidence = {
            "source": cand["source"],
            "fill": round(float(fill), 3),
            "holes": self._hole_count(ctx, bbox),
        }
        if "ring" in cand:
            evidence["ring"] = round(float(cand["ring"]), 3)
        judged = None
        if fill <= self.staff.head_fill_hollow_max:
            judged = "hollow"
        elif fill >= self.staff.head_fill_filled_min:
            judged = "filled"
        label = cand["label"]
        if judged is not None and judged != label:
            evidence["fill_says"] = judged
            result = None
            if templates is not None:
                result = templates.classify(self._patch(ctx, bbox), self.staff.template_ncc_min)
            if result is None:
                evidence["conflict"] = True
                return None
            label, score = result
            evidence["template"] = {"label": label, "ncc": round(float(score), 3)}
        evidence["label"] = label
        return label, evidence

    def _drop_conflicts(self, candidates: list[dict]) -> list[dict]:
        """同一条符头被两条支路都抓到（框明显重叠）说明有歧义，两条都丢掉。"""
        kept: list[dict] = []
        dropped: set[int] = set()
        for i, left in enumerate(candidates):
            for j in range(i + 1, len(candidates)):
                if j in dropped:
                    continue
                right = candidates[j]
                if _iou(left["bbox"], right["bbox"]) > 0.3:
                    dropped.add(i)
                    dropped.add(j)
                    break
        for index, cand in enumerate(candidates):
            if index not in dropped:
                kept.append(cand)
        return kept


def _iou(left, right) -> float:
    ix0, iy0 = max(left[0], right[0]), max(left[1], right[1])
    ix1, iy1 = min(left[2], right[2]), min(left[3], right[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_left = (left[2] - left[0]) * (left[3] - left[1])
    area_right = (right[2] - right[0]) * (right[3] - right[1])
    return inter / max(1.0, area_left + area_right - inter)
