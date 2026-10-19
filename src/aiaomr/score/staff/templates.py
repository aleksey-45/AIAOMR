"""本页自举符头模板，用 `TM_CCOEFF_NORMED` 做空心/实心的复核（`spec-staff.md` SR-22、ST-05）。

两条硬约束：
- **自举**：模板只能从本页/本窗口已经判过类的候选里取，不落盘、不依赖外部字体文件；
- **确定性**：同一批候选、同一顺序，模板必须一样（medoid = 与同类其它候选平均 NCC 最高的那个）。

本模块只做"归一化 + 取 medoid + 打分"，不碰几何阈值；阈值由调用方从 `cfg.staff.template_ncc_min` 传入。
"""

from __future__ import annotations

import cv2
import numpy as np

# 归一化后的模板尺寸（像素）。这是形状比较的画布大小，不是判据阈值。
NORM_W = 24
NORM_H = 16


def normalize(ink: np.ndarray) -> np.ndarray:
    """把一个候选的墨迹裁到外接框，缩放到固定画布，返回 0/255 的二值图。"""
    mask = ink.astype(bool)
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return np.zeros((NORM_H, NORM_W), np.uint8)
    crop = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1].astype(np.uint8) * 255
    resized = cv2.resize(crop, (NORM_W, NORM_H), interpolation=cv2.INTER_AREA)
    return (resized > 127).astype(np.uint8) * 255


def _score(canvas: np.ndarray, template: np.ndarray) -> float:
    """两张 0/255 图的 NCC 分数；两边一样大时 matchTemplate 退化成 1×1。"""
    if canvas.shape[0] < template.shape[0] or canvas.shape[1] < template.shape[1]:
        return 0.0
    result = cv2.matchTemplate(canvas, template, cv2.TM_CCOEFF_NORMED)
    if not np.isfinite(result).all():
        return 0.0
    return float(result.max())


class HeadTemplates:
    """两类符头模板（空心 / 实心）。只有两类都自举成功时才能用于复核。"""

    def __init__(self, templates: dict[str, np.ndarray]) -> None:
        self.templates = dict(sorted(templates.items()))

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(self.templates)

    @classmethod
    def bootstrap(cls, labelled: dict[str, list[np.ndarray]]) -> "HeadTemplates | None":
        """按类别取 medoid。`labelled` 是 类别 → 归一化后的候选墨迹列表。"""
        templates: dict[str, np.ndarray] = {}
        for label, patches in labelled.items():
            patches = [patch for patch in patches if patch is not None and patch.size]
            if not patches:
                continue
            best_index = 0
            best_mean = -1.0
            for index, patch in enumerate(patches):
                scores = [
                    _score(patch, other) for other_index, other in enumerate(patches) if other_index != index
                ]
                mean = float(np.mean(scores)) if scores else 1.0
                if mean > best_mean:
                    best_mean, best_index = mean, index
            templates[label] = patches[best_index]
        if set(templates) != {"hollow", "filled"}:
            return None
        return cls(templates)

    def classify(self, ink: np.ndarray, ncc_min: float) -> tuple[str, float] | None:
        """返回 (类别, NCC)；两类分不开或分数低于下限时返回 None（调用方 abstain）。"""
        patch = normalize(ink)
        if not patch.any():
            return None
        scores = {label: _score(patch, template) for label, template in self.templates.items()}
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        best_label, best_score = ranked[0]
        second = ranked[1][1]
        if best_score < ncc_min:
            return None
        # 两类分数太近说明模板分辨不了这个形状，不要硬选。
        if best_score - second < 0.05:
            return None
        return best_label, best_score
