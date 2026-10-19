"""几何定弦号：品数数字的纵向位置 → TAB 弦线 → IR 弦号（RD-06b）。"""

from __future__ import annotations

from aiaomr.measure.read import string_from_digit_y

CROP = [0.0, 100.0, 1000.0, 400.0]      # 裁片高 300 px
TAB_LINES = [200.0, 240.0, 280.0, 320.0]  # 4 条线，间距 40 px，最上面 = 最高音弦
COUNT = 4


def test_digit_on_top_line_is_highest_ir_string() -> None:
    # 数字中心正好在第 1 条线（y=200）→ 最上面那条 = IR 第 4 弦
    assert string_from_digit_y((200.0 - 100.0) / 300.0, TAB_LINES, CROP, COUNT) == 4


def test_digit_on_bottom_line_is_lowest_ir_string() -> None:
    assert string_from_digit_y((320.0 - 100.0) / 300.0, TAB_LINES, CROP, COUNT) == 1


def test_digit_slightly_off_line_still_maps() -> None:
    # 离第 3 条线 8 px（< 半个间距 20 px）仍然算第 3 条线
    assert string_from_digit_y((288.0 - 100.0) / 300.0, TAB_LINES, CROP, COUNT) == 2


def test_digit_between_lines_is_ambiguous() -> None:
    # 正好在两条线中间（偏差 20 px = 半个间距）不硬猜
    assert string_from_digit_y((260.0 - 100.0) / 300.0, TAB_LINES, CROP, COUNT) is None


def test_no_tab_lines_falls_back() -> None:
    assert string_from_digit_y(0.5, [], CROP, COUNT) is None
