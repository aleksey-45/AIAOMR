"""TAB 数字的几何定位：按已知弦线作参考，给每个品数数字定出弦号。

不抹线、不猜形状：已知弦线的行号只当参考系和掩码——统计墨迹时跳过线所在的行，
剩下的墨迹就是数字（以及可能的技术符号）。数字块的纵向中心落在哪条弦线附近，
那个弦就是它的弦号（IR 约定：1 = 最低音弦）。

接口只吃像素数组与裁片坐标系里的弦线位置，不认识模型、不读文件，便于单测。
"""

from __future__ import annotations

import numpy as np


def _ink(image: np.ndarray) -> np.ndarray:
    """深色墨迹。裁片是白底黑字，取灰度中点做阈值即可（不依赖局部光照假设）。"""
    low, high = float(image.min()), float(image.max())
    if high - low < 8:  # 整张图几乎没有墨迹
        return np.zeros_like(image, dtype=bool)
    cut = (low + high) / 2.0
    return image < cut


def _merge_runs(runs: list[list[int]], max_gap: int) -> list[list[int]]:
    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][-1] <= max_gap:
            merged[-1] = [merged[-1][0], run[-1]]
        else:
            merged.append(run)
    return merged


def detect_digits(
    image: np.ndarray,
    tab_lines: list[float],
    string_count: int,
    *,
    strip_x: float = 0.0,
) -> list[tuple[float, int]]:
    """返回 `[(中心 x, 弦号)]`，按 x 升序。

    `tab_lines` 是**裁片坐标系**里的弦线 y（自上而下，第一条 = 最高音弦）；
    `strip_x` 是左侧引用条的宽度，条内不参与检测。
    """
    image = np.asarray(image.convert("L") if hasattr(image, "convert") else image, dtype=np.float32)
    if not tab_lines or len(tab_lines) < 2 or image.size == 0:
        return []
    spacing = float(np.median(np.diff(sorted(tab_lines))))
    if spacing <= 1:
        return []

    ink = _ink(image)
    # 线所在的行只当参考：先从行覆盖估出整条线的厚度，再从计数里剔除这些行。
    # 像素本身保留，不抹线、不破坏压线的数字。
    coverage = ink.mean(axis=1)
    for line in tab_lines:
        row = int(round(line))
        top = row
        while top - 1 >= 0 and coverage[top - 1] > 0.5:
            top -= 1
        bottom = row
        while bottom + 1 < coverage.shape[0] and coverage[bottom + 1] > 0.5:
            bottom += 1
        ink[max(0, top - 1) : min(ink.shape[0], bottom + 2), :] = False

    start_col = int(max(0, round(strip_x)))
    if start_col >= ink.shape[1]:
        return []
    band = ink[:, start_col:]

    columns = band.sum(axis=0)
    runs: list[list[int]] = []
    for column in np.flatnonzero(columns > 0):
        column = int(column)
        if runs and column - runs[-1][-1] <= 1:
            runs[-1][-1] = column
        else:
            runs.append([column, column])
    # 双字形（11、12）以及挨得近的技术符号：按 x 间隔合并成"一个数字"
    runs = _merge_runs(runs, max_gap=max(1, int(round(0.35 * spacing))))

    out: list[tuple[float, int]] = []
    for left, right in runs:
        width = right - left + 1
        rows = np.flatnonzero(band[:, left : right + 1].sum(axis=1) > 0)
        if rows.size == 0:
            continue
        height = int(rows[-1] - rows[0] + 1)
        if not (0.10 * spacing <= width <= 1.3 * spacing):
            continue
        if not (0.20 * spacing <= height <= 1.5 * spacing):
            continue
        center_y = float(rows.mean())
        line_index = int(np.argmin([abs(center_y - float(line)) for line in tab_lines]))
        out.append((float((left + right) / 2 + start_col), string_count - line_index))
    return out
