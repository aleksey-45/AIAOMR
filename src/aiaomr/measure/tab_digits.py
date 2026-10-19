"""TAB 数字的几何定位：一切用"真边框内的百分比"，不用像素坐标换算。

真边框 = 五线谱上沿到 TAB 下沿（不含裁片外拓）。裁片是在这个真边框外面再外拓得到的，
所以真边框在裁片里的位置是**比例**，不需要知道缩放比、也不需要页面坐标：

    top_frac    = 2格 / 总高度（总高度 = 内容 + 2格 + 1格）
    bottom_frac = (内容 + 2格) / 总高度

弦线在真边框内的位置同样是比例。检测时：这些比例只用于"认领"裁片里真实存在的整行墨迹
（行投影，与定位层同款办法），再拿真实行做掩码；剩下的墨迹按列投影找数字块，数字块中心
换算成真边框内的比例，离哪条弦线比例最近就属于哪条弦。全程没有绝对坐标、没有缩放比。
"""

from __future__ import annotations

import numpy as np


def _ink(image: np.ndarray) -> np.ndarray:
    low, high = float(image.min()), float(image.max())
    if high - low < 8:
        return np.zeros_like(image, dtype=bool)
    return image < (low + high) / 2.0


def _line_rows(ink: np.ndarray, strip_frac: float) -> list[tuple[int, int]]:
    """主区域里"整行都是墨"的行 run（谱线）——和定位层找谱线是同一个办法。"""
    width = ink.shape[1]
    start = int(round(strip_frac * width))
    band = ink[:, start:]
    if band.size == 0:
        return []
    rows = np.flatnonzero(band.mean(axis=1) > 0.5)
    runs: list[tuple[int, int]] = []
    for row in rows:
        row = int(row)
        if runs and row - runs[-1][1] <= 1:
            runs[-1] = (runs[-1][0], row)
        else:
            runs.append((row, row))
    return runs


def detect_digits(
    image: np.ndarray,
    tab_fracs: list[float],
    string_count: int,
    *,
    top_frac: float,
    bottom_frac: float,
    strip_frac: float = 0.0,
    tol_frac: float = 0.03,
) -> list[tuple[float, int]]:
    """返回 `[(真边框内的 x 比例, 弦号)]`，按 x 升序。

    `tab_fracs`：弦线在真边框内的纵向比例，自上而下（第一条 = 最高音弦）。
    `top_frac` / `bottom_frac`：真边框在整张裁片里的上下边界比例。
    `strip_frac`：左侧引用条占整张裁片宽度的比例，条内不检测。
    """
    image = np.asarray(image, dtype=np.float32)
    height, width = image.shape
    if width <= 2 or height <= 2 or not tab_fracs or len(tab_fracs) < 2:
        return []
    span = bottom_frac - top_frac
    if span <= 0.05:
        return []
    ink = _ink(image)

    # 1) 用比例去"认领"裁片里真实的整行墨迹（行投影，与定位层同款办法）。
    expected = [top_frac + frac * span for frac in tab_fracs]
    runs = _line_rows(ink, strip_frac)
    chosen: list[tuple[float, int, int]] = []
    for frac in expected:
        best = None
        for top, bottom in runs:
            center = (top + bottom) / 2.0 / height
            if abs(center - frac) <= tol_frac and (best is None or abs(center - frac) < abs(best[0] - frac)):
                best = (center, top, bottom)
        if best is None:
            return []  # 线认不齐就不猜，交给上层回退
        chosen.append(best)

    # 2) 真实线行只当掩码：跳过这些行统计墨迹，压线数字也不会被切断。
    for _center, top, bottom in chosen:
        # 线有抗锯齿边，掩码要比检测到的厚度再宽 2 行，否则每列都会残留墨迹
        ink[max(0, top - 4) : min(height, bottom + 5), :] = False

    # 3) 列投影找数字块，中心换算成真边框内的比例，归到最近的弦线比例。
    start_col = int(round(strip_frac * width))
    band = ink[:, start_col:]
    columns = band.sum(axis=0)
    runs_x: list[list[int]] = []
    for column in np.flatnonzero(columns > 0):
        column = int(column)
        if runs_x and column - runs_x[-1][1] <= 1:
            runs_x[-1][1] = column
        else:
            runs_x.append([column, column])
    spacing = float(np.median(np.diff(sorted(tab_fracs)))) * span * height
    if spacing <= 1:
        return []
    merged: list[list[int]] = []
    for run in runs_x:
        if merged and run[0] - merged[-1][1] <= max(1, int(round(0.35 * spacing))):
            merged[-1][1] = run[1]
        else:
            merged.append(list(run))

    main_width = width - start_col
    out: list[tuple[float, int]] = []
    for left, right in merged:
        block = band[:, left : right + 1]
        rows = np.flatnonzero(block.sum(axis=1) > 0)
        if rows.size == 0:
            continue
        width_px = right - left + 1
        height_px = int(rows[-1] - rows[0] + 1)
        if not (0.10 * spacing <= width_px <= 1.3 * spacing):
            continue
        if not (0.20 * spacing <= height_px <= 1.5 * spacing):
            continue
        center_frac = (float(rows.mean()) / height - top_frac) / span
        line_index = int(np.argmin([abs(center_frac - frac) for frac in tab_fracs]))
        x_frac = float((left + right) / 2.0) / max(1, main_width)
        out.append((x_frac, string_count - line_index))
    return out
