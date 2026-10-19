"""归属的测试（`docs/spec-staff.md` SR-40..46）。

用手画的页面验证三件事：横梁段合并成线、每根符干的横梁条数按入射条数算、符头符干配对。
"""

from __future__ import annotations

import numpy as np

from aiaomr.kernel.contracts import MeasureBox, System
from aiaomr.score.staff.beams import BeamCriterion, FlagCriterion
from aiaomr.score.staff.context import measure_context
from aiaomr.score.staff.group import group_notes
from aiaomr.score.staff.heads import HeadCriterion
from aiaomr.score.staff.stems import StemCriterion

DEG = 12
STAFF_TOP = 20


def _page(width: int = 200, height: int = 140) -> np.ndarray:
    return np.full((height, width), 255, dtype=np.uint8)


def _staff(arr: np.ndarray) -> None:
    for line in range(5):
        y = STAFF_TOP + line * DEG
        arr[y : y + 2, 4 : arr.shape[1] - 4] = 0


def _stem(arr: np.ndarray, x: int, top: int, bottom: int) -> None:
    arr[top:bottom, x : x + 2] = 0


def _head(
    arr: np.ndarray, cx: int, cy: int, *, hollow: bool = False, rx: int = 7, ry: int = 5,
    thickness: float = 2.2,
) -> None:

    ys = range(cy - ry - 1, cy + ry + 2)
    xs = range(cx - rx - 1, cx + rx + 2)
    for y in ys:
        for x in xs:
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                arr[y, x] = 0
    if hollow:
        for y in ys:
            for x in xs:
                if ((x - cx) / (rx - thickness)) ** 2 + ((y - cy) / (ry - thickness)) ** 2 <= 1.0:
                    arr[y, x] = 255


def _beam(arr: np.ndarray, x0: int, x1: int, y: int, thickness: int = 5) -> None:
    arr[y : y + thickness, x0:x1] = 0


def _context(arr: np.ndarray):
    width = arr.shape[1]
    system = System(
        id=1, page=0, y0=float(STAFF_TOP), y1=float(STAFF_TOP + 4 * DEG),
        tabY0=0.0, tabY1=0.0, tabLines=[], measures=[],
        headerX0=0.0, headerX1=float(width),
    )
    box = MeasureBox(index=1, printed=None, x0=4.0, x1=float(width - 4), width=float(width - 8))
    # 归属单测不关心小节边界，窗口不外扩（边界处理在 test_staff_read 里测）。
    return measure_context(arr, system, box, DEG, x_margin_deg=0)


def _group(arr: np.ndarray):
    ctx = _context(arr)
    findings: dict[str, list] = {}
    findings["stem"] = StemCriterion().detect(ctx, findings)
    findings["beam"] = BeamCriterion().detect(ctx, findings)
    findings["flag"] = FlagCriterion().detect(ctx, findings)
    findings["head"] = HeadCriterion().detect(ctx, findings)
    grouping = group_notes(ctx, findings)
    return ctx, findings, grouping


def _three_stem_page(second_beam_from: int | None = None) -> np.ndarray:
    """三根符干 + 一条横梁；`second_beam_from` 给第二根横梁（二级横梁）的起点。"""
    arr = _page()
    _staff(arr)
    tops = [8, 8, 8]
    for x in (40, 90, 140):
        _stem(arr, x, tops[0], STAFF_TOP + 3 * DEG)
        _head(arr, x - 6, STAFF_TOP + 3 * DEG, hollow=False)
    _beam(arr, 40, 142, 8)
    if second_beam_from is not None:
        _beam(arr, second_beam_from, 142, 17)  # 避开 y=20 的谱线，否则会被抹线吃掉
    return arr


def test_single_beam_line_counts_once_per_stem() -> None:
    """一条横梁跨三根符干：合并成一条线，每根符干只算一条横梁（不能被数成两条）。"""
    ctx, findings, grouping = _group(_three_stem_page())

    assert len(findings["stem"]) == 3
    # 窗口坐标：画在页面 x=40 的东西进窗口后是 36（窗口左边留了 4 像素）。
    beams = {round(glyph.x): glyph.beams for glyph in grouping.glyphs}
    assert beams == {36: 1, 86: 1, 136: 1}
    assert len({glyph.group for glyph in grouping.glyphs}) == 1


def test_partial_second_beam_starts_at_the_second_note() -> None:
    """前八后十六：二级横梁只从第二个音符开始，第一个音符仍是一条（八分）。"""
    _ctx, _findings, grouping = _group(_three_stem_page(second_beam_from=90))

    beams = {round(glyph.x): glyph.beams for glyph in grouping.glyphs}
    assert beams == {36: 1, 86: 2, 136: 2}
    durations = {
        round(glyph.x): "eighth" if glyph.beams == 1 else "16th"
        for glyph in grouping.glyphs
    }
    assert durations == {36: "eighth", 86: "16th", 136: "16th"}


def test_whole_note_has_no_stem() -> None:
    arr = _page()
    _staff(arr)
    # 全音符画在两线之间，环比实心符头大一点（deg=12 时符头本身很小，环太薄会被当成噪点）。
    _head(arr, 60, STAFF_TOP + 2 * DEG + DEG // 2, hollow=True, rx=9, ry=6, thickness=2.6)

    _ctx, _findings, grouping = _group(arr)

    assert len(grouping.glyphs) == 1
    glyph = grouping.glyphs[0]
    assert glyph.stem is None
    assert glyph.head_class == "hollow"


def test_chord_heads_share_one_stem() -> None:
    arr = _page()
    _staff(arr)
    _stem(arr, 40, 8, STAFF_TOP + 3 * DEG)
    _head(arr, 34, STAFF_TOP + 3 * DEG)
    _head(arr, 34, STAFF_TOP + 2 * DEG)

    _ctx, _findings, grouping = _group(arr)

    assert len(grouping.glyphs) == 1
    assert len(grouping.glyphs[0].heads) == 2


def test_flagged_stem_gets_beam_count_from_flag() -> None:
    arr = _page()
    _staff(arr)
    _stem(arr, 40, 8, STAFF_TOP + 3 * DEG)
    _head(arr, 34, STAFF_TOP + 3 * DEG)
    _beam(arr, 42, 60, 10, thickness=5)  # 符干顶端右侧的钩

    _ctx, _findings, grouping = _group(arr)

    assert grouping.glyphs[0].flags == 1
    assert grouping.glyphs[0].beams == 0

