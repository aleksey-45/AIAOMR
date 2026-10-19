"""系统切分的测试（规格 §2.1 R-02、R-08；计划任务 4 的三个用例）。"""

from __future__ import annotations

import numpy as np

from aiaomr.score.locate.systems import find_systems, staff_lines, row_groups
from tests.fixtures.pages import page_with_systems, with_thick_band


def test_finds_three_systems() -> None:
    """一张画着三组谱表的页面，必须找到三个系统，且 TAB 带在谱带下方。"""
    arr = page_with_systems(n_systems=3, deg=12, tab_spacing=18)
    systems = find_systems(arr, arr.shape[1])

    assert len(systems) == 3
    for system in systems:
        assert len(system.tabLines) == 4
        assert system.tabY0 > system.y1
        spacing = float(np.mean(np.diff(system.tabLines)))
        assert abs(spacing - 18) <= 2


def test_short_last_line_is_found() -> None:
    """最后一行只画到页面三成四，仍然必须找到（评审重点第一条，R-08）。"""
    arr = page_with_systems(n_systems=3, last_frac=0.34)
    systems = find_systems(arr, arr.shape[1])

    assert len(systems) == 3
    last = systems[-1]
    assert last.y0 > systems[0].y1


def test_thick_black_band_is_not_a_staff_line() -> None:
    """一条四十像素粗、贯穿页面的黑边，不能被当成谱线。"""
    arr = with_thick_band(page_with_systems(n_systems=2), y=0, thickness=40)
    lines = staff_lines(arr)

    assert len(lines) == 18  # 2 个系统 × (5 + 4) 条线
    systems = find_systems(arr, arr.shape[1])
    assert len(systems) == 2
    mask = np.zeros((10, 20), dtype=bool)
    mask[2, :] = True
    mask[7, :] = True
    mask[:, 8] = True
    mask[:, 15] = True

    rows = row_groups(mask, 0.9, axis=1)
    cols = row_groups(mask, 0.9, axis=0)
    assert rows == [2, 7]
    assert cols == [8, 15]
