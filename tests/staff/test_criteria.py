"""几何判据的单测：每条判据只回答"有没有、几个、在哪"（P2 任务 2）。"""

from __future__ import annotations

import numpy as np

from aiaomr.kernel.contracts import MeasureBox, System
from aiaomr.score.staff.beams import BeamCriterion
from aiaomr.score.staff.context import measure_context
from aiaomr.score.staff.dots import DotCriterion
from aiaomr.score.staff.heads import HeadCriterion
from aiaomr.score.staff.rests import RestBarCriterion
from aiaomr.score.staff.stems import StemCriterion
from tests.fixtures.rhythm_pages import rhythm_measure

DEG = 12


def _context(beats: list[dict]):
    arr = rhythm_measure(beats, deg=DEG)
    width = arr.shape[1]
    system = System(
        id=1, page=0, y0=60.0, y1=60.0 + 4 * DEG, tabY0=0.0, tabY1=0.0,
        tabLines=[], measures=[], headerX0=0.0, headerX1=float(width),
    )
    box = MeasureBox(index=1, printed=None, x0=float(DEG), x1=float(width - DEG),
                     width=float(width - 2 * DEG))
    # 判据单测不关心小节边界，窗口不外扩（边界处理在 test_staff_read 里测）。
    return measure_context(arr, system, box, DEG, x_margin_deg=0)


def test_stem_criterion_counts_stems() -> None:
    ctx = _context([{"kind": "note"}] * 4)
    stems = StemCriterion().detect(ctx)

    assert len(stems) == 4
    assert all(stem.kind == "stem" for stem in stems)


def test_beam_criterion_counts_one_beam_for_eighths() -> None:
    ctx = _context([{"kind": "note", "beams": 1}] * 4)
    findings = {"stem": StemCriterion().detect(ctx)}

    beams = BeamCriterion().detect(ctx, findings)

    assert len(beams) == 3
    assert all(int(beam.value) == 1 for beam in beams)


def test_dot_criterion_finds_one_dot() -> None:
    ctx = _context([{"kind": "note", "dots": 1}, {"kind": "note"}])
    findings = {"stem": StemCriterion().detect(ctx)}

    dots = DotCriterion().detect(ctx, findings)

    assert len(dots) == 1


def test_rest_bar_criterion_detects_multirest() -> None:
    arr = np.full((120, 200), 255, dtype=np.uint8)
    for line in range(5):
        arr[40 + line * DEG : 41 + line * DEG, 10:190] = 0
    # 多小节休止条：贯穿小节的粗横线
    arr[76:86, 10:190] = 0
    system = System(id=1, page=0, y0=40.0, y1=40.0 + 4 * DEG, tabY0=0.0, tabY1=0.0,
                    tabLines=[], measures=[], headerX0=0.0, headerX1=200.0)
    box = MeasureBox(index=1, printed=None, x0=10.0, x1=190.0, width=180.0)
    ctx = measure_context(arr, system, box, DEG)

    assert RestBarCriterion().detect(ctx)
