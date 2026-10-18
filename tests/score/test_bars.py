"""小节切分的测试（规格 §2.1 R-04；计划任务 5 的四个用例里前两个）。"""

from __future__ import annotations

import numpy as np

from aiaomr.score.locate.bars import find_bars
from tests.fixtures.pages import one_system_page, system_of


def test_bars_are_found_and_clef_is_not_a_bar() -> None:
    """三条小节线把系统切成三段；谱号区里的短竖线不能凭空变成一个小节。"""
    bars = (60, 500, 940, 1380)
    arr, bands = one_system_page(bars=bars, clef_x=80)
    system = system_of(bands, tab_spacing=18)

    boxes = find_bars(arr, system, deg=12.0)

    assert len(boxes) == 3
    assert boxes[0].x0 == 60
    assert boxes[-1].x1 == 1380
    # 谱号区（60..500 这段里的 80）并进第一小节，没有多出一个小节
    assert [box.index for box in boxes] == [1, 2, 3]


def test_bars_ignore_short_vertical_ticks() -> None:
    """多小节休止条两端的短竖线不贯穿 TAB 带，不能算小节线。"""
    arr, bands = one_system_page(bars=(60, 500, 940, 1380))
    # 在 TAB 带里只画一小段竖线（模拟休止条端头），不该被认成小节线
    arr[int(bands[2]) : int(bands[2]) + 10, 300] = 0
    system = system_of(bands, tab_spacing=18)

    boxes = find_bars(arr, system, deg=12.0)

    assert len(boxes) == 3
