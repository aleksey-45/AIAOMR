"""`measure/tab_digits.py`：弦线作参考（真边框百分比），为品数数字定弦号。"""

from __future__ import annotations

import numpy as np

from aiaomr.measure.tab_digits import detect_digits

HEIGHT = 400
TOP_FRAC = 0.20          # 真边框在裁片里的上界
BOTTOM_FRAC = 0.85       # 真边框在裁片里的下界
TAB_FRACS = [0.0, 1 / 3, 2 / 3, 1.0]   # 4 条弦线在真边框内的比例（上→下）


def _box_rows() -> list[float]:
    span = BOTTOM_FRAC - TOP_FRAC
    return [(TOP_FRAC + frac * span) * HEIGHT for frac in TAB_FRACS]


def _page(digits: list[tuple[int, float]]) -> np.ndarray:
    """白底 + 4 条横线 + 在 (x, 真边框内比例) 画 16x28 的数字块。"""
    image = np.full((HEIGHT, 500), 255, dtype=np.uint8)
    for row in _box_rows():
        image[int(round(row)) : int(round(row)) + 2, :] = 0
    span = BOTTOM_FRAC - TOP_FRAC
    for x, frac in digits:
        row = int(round((TOP_FRAC + frac * span) * HEIGHT))
        image[row - 14 : row + 14, x : x + 16] = 0
    return image


def _detect(image: np.ndarray, *, strip_frac: float = 0.0):
    return detect_digits(image, TAB_FRACS, 4, top_frac=TOP_FRAC, bottom_frac=BOTTOM_FRAC,
                         strip_frac=strip_frac)


def test_digit_on_first_and_last_line_maps_to_highest_and_lowest_string() -> None:
    image = _page([(100, 0.0), (300, 1.0)])

    found = _detect(image)

    assert [string for _x, string in found] == [4, 1]


def test_digit_riding_a_line_still_maps_to_that_line() -> None:
    image = _page([(120, 1 / 3)])

    found = _detect(image)

    assert len(found) == 1
    assert found[0][1] == 3


def test_two_glyph_number_counts_as_one_digit() -> None:
    image = np.full((HEIGHT, 500), 255, dtype=np.uint8)
    for row in _box_rows():
        image[int(round(row)) : int(round(row)) + 2, :] = 0
    span = BOTTOM_FRAC - TOP_FRAC
    row = int(round((TOP_FRAC + (1 / 3) * span) * HEIGHT))
    image[row - 14 : row + 14, 100:112] = 0
    image[row - 14 : row + 14, 118:130] = 0
    image[row - 14 : row + 14, 300:312] = 0

    found = _detect(image)

    assert [string for _x, string in found] == [3, 3]


def test_strip_region_is_ignored() -> None:
    image = _page([(150, 1.0), (300, 1.0)])
    # 左边缘画一个"数字"，靠 strip 比例把它排除
    image[300:340, 5:20] = 0

    found = _detect(image, strip_frac=0.06)

    assert len(found) == 2
    assert all(x > 0.06 for x, _string in found)


def test_missing_line_returns_empty_instead_of_guessing() -> None:
    image = np.full((HEIGHT, 500), 255, dtype=np.uint8)
    # 只画 3 条线（缺一条），比例认领不上，直接返回空让上层回退
    for row in _box_rows()[:3]:
        image[int(round(row)) : int(round(row)) + 2, :] = 0

    assert _detect(image) == []
