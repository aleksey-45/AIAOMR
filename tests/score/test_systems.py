"""系统切分的测试（规格 §2.1 R-02、R-08；计划任务 4 的三个用例）。"""

from __future__ import annotations

import numpy as np

from aiaomr.score.locate.systems import find_systems, staff_line_runs, staff_lines, row_groups
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


def test_staff_line_runs_cover_the_full_line_thickness() -> None:
    """谱线是 3 px 厚时，行的 run 必须覆盖整条线，不能只给中心行（R-10、SR-11）。

    只拿到中心行的话，读谱层抹线时会把上下两条边沿留在图里，横梁判据会把它们
    当成两条横梁，整小节的音符都会被读成十六分。
    """
    arr = page_with_systems(n_systems=2, line_thickness=3)
    runs = staff_line_runs(arr)

    assert len(runs) == 18  # 2 个系统 × (5 + 4) 条线
    for top, bottom in runs:
        assert bottom - top + 1 == 3
    # 中心行与老接口一致，老调用方不用改。
    assert [float((top + bottom) // 2) for top, bottom in runs] == staff_lines(arr)


def test_a_thick_black_band_is_not_a_line_run() -> None:
    """四十像素粗的黑边不能被当成谱线，run 口径下也一样。"""
    arr = with_thick_band(page_with_systems(n_systems=2), y=0, thickness=40)
    runs = staff_line_runs(arr)

    assert len(runs) == 18
    assert all(bottom - top + 1 <= 6 for top, bottom in runs)


def test_row_groups_respects_axis() -> None:
    """row_groups 沿指定轴找覆盖率高的行；两种轴都要能用。"""
    mask = np.zeros((10, 20), dtype=bool)
    mask[2, :] = True
    mask[7, :] = True
    mask[:, 8] = True
    mask[:, 15] = True

    rows = row_groups(mask, 0.9, axis=1)
    cols = row_groups(mask, 0.9, axis=0)
    assert rows == [2, 7]
    assert cols == [8, 15]


def test_systems_carry_staff_line_runs() -> None:
    """每个系统必须交出五线谱那 5 条线的行 run（R-10），读谱层靠它按整条线厚抹线。"""
    arr = page_with_systems(n_systems=2, line_thickness=3)
    systems = find_systems(arr, arr.shape[1])

    for system in systems:
        assert len(system.staffLines) == 5
        assert [line.center for line in system.staffLines] == [
            system.y0 + 12 * index for index in range(5)
        ]
        assert all(line.bottom - line.top + 1 == 3 for line in system.staffLines)
