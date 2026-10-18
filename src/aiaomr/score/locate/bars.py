"""找小节线，把系统切成小节（规格 §2.1 R-04、§2.4 RD-01）。

小节线只按"在 TAB 带里贯穿"来认：TAB 带里除了小节线没有别的东西会从上到下贯穿，
谱号、拍号、音符、连音线都不会。这样不会被谱号区骗出一条假的系统边线。
"""

from __future__ import annotations

import numpy as np

from ...kernel.contracts import MeasureBox, System
from .systems import adaptive_cut

# 一条竖线要在 TAB 带里覆盖这么多行，才算小节线。
_BAR_COVERAGE = 0.75
# 同一批候选列聚成一个中心的容差。
_COL_MERGE_GAP = 3


def bar_columns(arr: np.ndarray, system: System) -> list[int]:
    """返回系统内小节线的 x 坐标（升序，含系统首尾两条）。"""
    top = max(0, int(round(system.tabY0)) - 2)
    bottom = min(arr.shape[0], int(round(system.tabY1)) + 3)
    if bottom - top < 4:
        return []
    band = arr[top:bottom] < adaptive_cut(arr)
    coverage = band.mean(axis=0)
    columns = np.flatnonzero(coverage > _BAR_COVERAGE)

    groups: list[list[int]] = []
    for column in columns:
        column = int(column)
        if groups and column - groups[-1][-1] <= _COL_MERGE_GAP:
            groups[-1].append(column)
        else:
            groups.append([column])
    centers = [int(round(float(np.mean(group)))) for group in groups]
    if len(centers) < 2:
        return []

    # 多小节休止条的两端短竖线也会贯穿 TAB 带；离下一条线不到半小节宽的，当噪声去掉。
    # 判哪条是噪声：它离上一条够远、离下一条太近，那它就是休止条的端头。
    gaps = [right - left for left, right in zip(centers, centers[1:])]
    half = 0.5 * float(np.median(gaps))
    kept = [centers[0]]
    index = 1
    while index < len(centers):
        too_close_to_next = index + 1 < len(centers) and centers[index + 1] - centers[index] < half
        far_from_kept = centers[index] - kept[-1] >= half
        if too_close_to_next and far_from_kept:
            index += 1  # 当前这条是噪声，下一条才是真小节线
            continue
        kept.append(centers[index])
        index += 1
    return kept


def find_bars(arr: np.ndarray, system: System, deg: float) -> list[MeasureBox]:
    """系统 → 小节框列表。

    第一个小节从系统首条竖线之后的谱号区开始，所以"谱号区"并进第一小节，
    不会凭空多出一个小节（评审重点之一，R-04）。
    """
    del deg  # 保留参数：调用方按 deg 校验宽度，便于以后换阈值口径
    columns = bar_columns(arr, system)
    boxes: list[MeasureBox] = []
    for index, (left, right) in enumerate(zip(columns, columns[1:]), start=1):
        boxes.append(
            MeasureBox(
                index=index,
                printed=None,
                x0=float(left),
                x1=float(right),
                width=float(right - left),
            )
        )
    return boxes
