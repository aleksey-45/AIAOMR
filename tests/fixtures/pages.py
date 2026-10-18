"""合成页面：给定位层的测试用 numpy 现画，不依赖真实图片。"""

from __future__ import annotations

import numpy as np


def page_with_systems(
    n_systems: int = 3,
    width: int = 1600,
    height: int = 1800,
    deg: int = 12,
    tab_spacing: int = 18,
    tab_gap_deg: float = 4.5,
    last_frac: float = 1.0,
    margin: int = 60,
    system_gap: int = 160,
) -> np.ndarray:
    """画一张白底页面，每行系统 = 5 条谱线 + 4 条 TAB 线。

    `last_frac` < 0.5 用来模拟"最后一行只占页面三成多宽"的短末行。
    """
    arr = np.full((height, width), 255, dtype=np.uint8)
    y = margin
    for index in range(n_systems):
        is_last = index == n_systems - 1
        ink_width = int(round(width * last_frac)) if is_last else width - margin * 2
        x0 = margin
        for line in range(5):
            arr[y + line * deg, x0:x0 + ink_width] = 0
        tab_top = y + 4 * deg + int(round(tab_gap_deg * deg))
        for line in range(4):
            arr[tab_top + line * tab_spacing, x0:x0 + ink_width] = 0
        y = tab_top + 3 * tab_spacing + system_gap
    return arr


def with_thick_band(arr: np.ndarray, y: int = 40, thickness: int = 40) -> np.ndarray:
    """在上方加一条贯穿页面的黑边（视频播放条、信纸阴影之类）。"""
    out = arr.copy()
    out[y : y + thickness, :] = 0
    return out


def one_system_page(
    width: int = 1600,
    height: int = 420,
    deg: int = 12,
    tab_spacing: int = 18,
    tab_gap_deg: float = 4.5,
    margin: int = 60,
    bars: tuple[int, ...] = (),
    clef_x: int | None = None,
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """一页一个系统，带小节竖线；返回图和 (谱线上, 谱线下, TAB 上, TAB 下)。"""
    arr = page_with_systems(
        1,
        width=width,
        height=height,
        deg=deg,
        tab_spacing=tab_spacing,
        tab_gap_deg=tab_gap_deg,
        margin=margin,
    )
    note_top = margin
    note_bottom = margin + 4 * deg
    tab_top = note_bottom + int(round(tab_gap_deg * deg))
    tab_bottom = tab_top + 3 * tab_spacing
    for x in bars:
        arr[note_top : tab_bottom + 1, x] = 0
    if clef_x is not None:
        # 谱号只画在五线谱带里：它不该被当成小节线
        arr[note_top : note_bottom + 1, clef_x] = 0
    return arr, (note_top, note_bottom, tab_top, tab_bottom)


def system_of(
    bands: tuple[int, int, int, int],
    tab_spacing: int,
    system_id: int = 1,
    page_width: int = 1600,
):
    """按合成页面的四个 y 坐标造一个 `System`。"""
    from aiaomr.kernel.contracts import System

    note_top, note_bottom, tab_top, tab_bottom = bands
    tab_lines = [float(tab_top + k * tab_spacing) for k in range(4)]
    return System(
        id=system_id,
        page=0,
        y0=float(note_top),
        y1=float(note_bottom),
        tabY0=float(tab_top),
        tabY1=float(tab_bottom),
        tabLines=tab_lines,
        measures=[],
        headerX0=0.0,
        headerX1=float(page_width),
    )
