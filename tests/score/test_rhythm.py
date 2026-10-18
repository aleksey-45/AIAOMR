"""几何节奏的测试（规格 §2.1；P2 任务 2）。"""

from __future__ import annotations

import numpy as np

from aiaomr.kernel.contracts import MeasureBox, System
from aiaomr.score.locate.rhythm import read_measure_rhythm
from tests.fixtures.rhythm_pages import rhythm_measure

DEG = 12


def _measure(beats: list[dict], expected_ticks: int | None = None):
    arr = rhythm_measure(beats, deg=DEG)
    width = arr.shape[1]
    system = System(
        id=1, page=0, y0=60.0, y1=60.0 + 4 * DEG, tabY0=0.0, tabY1=0.0,
        tabLines=[], measures=[], headerX0=0.0, headerX1=float(width),
    )
    box = MeasureBox(index=1, printed=None, x0=float(DEG), x1=float(width - DEG),
                     width=float(width - 2 * DEG))
    return read_measure_rhythm(arr, system, box, deg=DEG, expected_ticks=expected_ticks)


def test_four_quarters() -> None:
    shapes = _measure([{"kind": "note"}] * 4, expected_ticks=32)

    assert [shape.duration for shape in shapes] == ["quarter"] * 4
    assert all(shape.dots == 0 for shape in shapes)


def test_four_beamed_eighths() -> None:
    shapes = _measure([{"kind": "note", "beams": 1}] * 4, expected_ticks=16)

    assert [shape.duration for shape in shapes] == ["eighth"] * 4


def test_dotted_quarter_and_flagged_eighth() -> None:
    shapes = _measure([{"kind": "note", "dots": 1}, {"kind": "note", "beams": 1}],
                      expected_ticks=16)

    assert [shape.duration for shape in shapes] == ["quarter", "eighth"]
    assert shapes[0].dots == 1


def test_whole_note_has_no_stem() -> None:
    shapes = _measure([{"kind": "whole"}], expected_ticks=32)

    assert shapes and shapes[0].duration == "whole"


def test_sum_mismatch_falls_back_to_unknown() -> None:
    """三拍拼不成 4/4：不许硬凑，整小节退回 unknown 交给模型。"""
    shapes = _measure([{"kind": "note"}] * 3, expected_ticks=32)

    assert shapes
    assert all(shape.duration == "unknown" for shape in shapes)
