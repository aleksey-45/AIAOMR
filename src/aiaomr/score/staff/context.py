"""读谱层的公共上下文：一张谱、一个系统、一个小节窗口里，先算好所有共享的掩码。

依据：`docs/spec-staff.md` §4（SR-10..15）。两条和旧实现的差别：

- 窗口按**谱表分带**：上下留出符干、横梁、加线的余量，但下界不越过 TAB 带；
- 谱线按**整条线厚**抹掉（SR-11）。只抹中心行的话，上下两条边沿会留在图里，
  横梁判据会把它们当成两条横梁，整小节的音符都会被读成十六分（真页面实测）。

判据（`heads.py`、`stems.py` 等）只读这个对象，不再各自重算阈值、行位置和掩码。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ...kernel.config import load_staff_config
from ...kernel.contracts import MeasureBox, System
from ..locate.systems import adaptive_cut, staff_line_runs


@dataclass
class GeoContext:
    """一个小节窗口的几何上下文。坐标都是窗口内相对坐标，`line_rows` 是窗口内的中心行。"""

    dark: np.ndarray          # 原始二值：谱线在，符干连续
    beam_dark: np.ndarray     # 按整条线厚抹过谱线：量连梁、符尾、附点用
    line_rows: list[int]      # 谱线中心行的 y（窗口相对）
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


def _empty(left: int, top: int, width: int, height: int, deg: float) -> GeoContext:
    return GeoContext(
        dark=np.zeros((0, 0), dtype=bool),
        beam_dark=np.zeros((0, 0), dtype=bool),
        line_rows=[],
        deg=float(deg),
        left=left,
        top=top,
        width=max(0, width),
        height=max(0, height),
    )


def staff_band(system: System, deg: float, margin_deg: float | None = None) -> tuple[int, int]:
    """五线谱带的纵向范围（SR-10）：上留余量给符干和横梁，下界不越过 TAB 带。

    `margin_deg` 不给时取 `cfg.staff.band_margin_deg`（spec-v3 §5）。
    """
    if margin_deg is None:
        margin_deg = load_staff_config().band_margin_deg
    top = int(system.y0 - margin_deg * deg)
    bottom = int(system.y1 + margin_deg * deg)
    if system.tabY0 > system.y1:
        bottom = min(bottom, int(system.tabY0) - 2)
    return top, bottom


def measure_context(
    arr: np.ndarray,
    system: System,
    measure_box: MeasureBox,
    deg: float,
    margin_deg: float | None = None,
    erase_pad_px: int | None = None,
    line_runs: list[tuple[int, int]] | None = None,
) -> GeoContext:
    """建一个小节窗口的几何上下文。

    `line_runs` 是定位层交出的谱线行 run（R-10，页面坐标）；不给就从本窗口附近自己算。
    `margin_deg` / `erase_pad_px` 不给时取 `cfg.staff.band_margin_deg` / `cfg.staff.line_erase_pad_px`。
    """
    staff = load_staff_config()
    if margin_deg is None:
        margin_deg = staff.band_margin_deg
    if erase_pad_px is None:
        erase_pad_px = staff.line_erase_pad_px
    top, bottom = staff_band(system, deg, margin_deg)
    top = max(0, top)
    bottom = min(arr.shape[0], bottom)
    left = max(0, int(measure_box.x0))
    right = min(arr.shape[1], int(measure_box.x1))
    if bottom - top < 4 or right - left < 4:
        return _empty(left, top, right - left, bottom - top, deg)

    window = arr[top:bottom, left:right]
    dark = window < adaptive_cut(arr)

    probe_top = max(0, top - 2)
    probe = arr[probe_top : min(arr.shape[0], bottom + 2)]
    runs = line_runs if line_runs is not None else staff_line_runs(probe, frac=0.6)
    if runs:
        thickness = int(
            round(float(np.median([abs(int(b) - int(t)) + 1 for t, b in runs])))
        )
    else:
        thickness = 1
    half = max(1, thickness // 2)

    # 谱线位置用 System.y0/y1 的等距网格，不依赖 run 的分组：横梁贴着谱线时，
    # run 会把横梁和谱线合成一条粗线，那时按 run 抹线会把横梁一起抹掉。
    rows: list[int] = []
    beam_dark = dark.copy()
    for index in range(5):
        center = int(round(system.y0 + index * deg)) - top
        rows.append(center)
        for row in range(center - half - erase_pad_px, center + half + erase_pad_px + 1):
            if 0 <= row < beam_dark.shape[0]:
                beam_dark[row, :] = False

    return GeoContext(
        dark=dark,
        beam_dark=beam_dark,
        line_rows=rows,
        deg=float(deg),
        left=left,
        top=top,
        width=right - left,
        height=bottom - top,
    )
