"""`measure/tab_digits.py`：用已知弦线作参考，为品数数字定弦号。"""

from __future__ import annotations

import numpy as np

from aiaomr.measure.tab_digits import detect_digits


def _page(tab_lines: list[float], digits: list[tuple[int, int]]) -> np.ndarray:
    """白底、若干横线、在指定 (x, 行) 画 8x12 的数字块。"""
    height = int(max(tab_lines) + 60)
    width = 400
    image = np.full((height, width), 255, dtype=np.uint8)
    for line in tab_lines:
        image[int(round(line)) : int(round(line)) + 2, :] = 0
    for x, line in digits:
        row = int(round(line))
        image[row - 14 : row + 14, x : x + 16] = 0
    return image


def test_digit_block_maps_to_nearest_line() -> None:
    lines = [100.0, 150.0, 200.0, 250.0]
    image = _page(lines, [(100, 100.0), (200, 250.0)])

    found = detect_digits(image, lines, 4)

    assert [string for _x, string in found] == [4, 1]


def test_line_rows_do_not_count_as_ink_and_digit_riding_a_line_still_maps() -> None:
    lines = [100.0, 150.0, 200.0, 250.0]
    # 数字中心正好压在第 2 条线（150）上，应该映射到 IR 第 3 弦
    image = _page(lines, [(120, 150.0)])

    found = detect_digits(image, lines, 4)

    assert len(found) == 1
    assert found[0][1] == 3


def test_two_glyph_number_counts_as_one_digit() -> None:
    lines = [100.0, 150.0, 200.0, 250.0]
    image = np.full((320, 400), 255, dtype=np.uint8)
    for line in lines:
        image[int(line) : int(line) + 2, :] = 0
    image[196:224, 100:112] = 0   # "1"
    image[196:224, 118:130] = 0   # "2"，紧挨着
    image[196:224, 300:312] = 0

    found = detect_digits(image, lines, 4)

    assert [string for _x, string in found] == [2, 2]


def test_no_lines_or_tiny_image_returns_empty() -> None:
    assert detect_digits(np.full((100, 100), 255, np.uint8), [], 4) == []
    assert detect_digits(np.full((100, 100), 255, np.uint8), [50.0, 60.0], 4) == []
