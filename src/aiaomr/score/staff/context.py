"""几何判据的公共上下文：一张谱、一个系统、一个小节窗口里，先算好所有共享的掩码。

判据（criteria.py）只读这个对象，不再各自重算阈值、行位置和掩码，避免"同一个窗口
三份阈值"的老问题（旧项目每个 engraving 一个常量）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ...kernel.contracts import MeasureBox, System
from ..locate.systems import adaptive_cut, staff_lines


@dataclass
class GeoContext:
    """一个小节窗口的几何上下文。坐标都是窗口内相对坐标。"""

    dark: np.ndarray          # 原始二值：谱线在，符干连续
    beam_dark: np.ndarray     # 去掉谱线行：量连梁、符尾、附点用
    line_rows: list[int]      # 谱线行的 y（窗口相对）
    deg: float
    left: int
    top: int
    width: int
    height: int

    def clear_rows(self, rows: list[int]) -> np.ndarray:
        """在 `dark` 的副本上抹掉若干行，返回新图（不动原始上下文）。"""
        out = self.dark.copy()
        for row in rows:
            if 0 <= row < self.height:
                out[row, :] = False
        return out


def measure_context(
    arr: np.ndarray,
    system: System,
    measure_box: MeasureBox,
    deg: float,
) -> GeoContext:
    """建一个小节窗口的几何上下文。"""
    top = max(0, int(system.y0) - 3)
    bottom = min(arr.shape[0], int(system.y1) + 3)
    left = max(0, int(measure_box.x0))
    right = min(arr.shape[1], int(measure_box.x1))
    if bottom - top < 4 or right - left < 4:
        return GeoContext(
            dark=np.zeros((0, 0), dtype=bool),
            beam_dark=np.zeros((0, 0), dtype=bool),
            line_rows=[],
            deg=float(deg),
            left=left,
            top=top,
            width=max(0, right - left),
            height=max(0, bottom - top),
        )

    cut = adaptive_cut(arr)
    window = arr[top:bottom, left:right]
    dark = window < cut
    offset = max(0, top - 2)
    line_rows = [
        row + offset - top
        for row in staff_lines(
            arr[max(0, top - 2) : min(arr.shape[0], bottom + 2)], frac=0.6
        )
    ]
    beam_dark = dark.copy()
    for row in line_rows:
        if 0 <= row < beam_dark.shape[0]:
            beam_dark[row, :] = False
    return GeoContext(
        dark=dark,
        beam_dark=beam_dark,
        line_rows=line_rows,
        deg=float(deg),
        left=left,
        top=top,
        width=right - left,
        height=bottom - top,
    )
