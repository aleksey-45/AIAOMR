"""读谱编排的测试（`docs/spec-staff.md` §3、§7、§8、§9）。"""

from __future__ import annotations

import numpy as np

from aiaomr.kernel.contracts import MeasureBox, System
from aiaomr.score.staff.context import measure_context, staff_band
from aiaomr.score.staff.read import read_measure
from tests.fixtures.pages import one_system_page
from tests.fixtures.rhythm_pages import rhythm_measure

DEG = 12


def _system(arr: np.ndarray, staff_top: int = 60) -> System:
    width = arr.shape[1]
    return System(
        id=1, page=0, y0=float(staff_top), y1=float(staff_top + 4 * DEG),
        tabY0=0.0, tabY1=0.0, tabLines=[], measures=[],
        headerX0=0.0, headerX1=float(width),
    )


def _box(arr: np.ndarray) -> MeasureBox:
    width = arr.shape[1]
    return MeasureBox(index=1, printed=None, x0=float(DEG), x1=float(width - DEG),
                      width=float(width - 2 * DEG))


def _read(beats: list[dict], expected_ticks: int | None):
    arr = rhythm_measure(beats, deg=DEG)
    return read_measure(arr, _system(arr), _box(arr), DEG, expected_ticks=expected_ticks)


def test_four_quarters_are_ok() -> None:
    rhythm = _read([{"kind": "note"}] * 4, expected_ticks=32)

    assert rhythm.status == "ok"
    assert rhythm.ticks == 32
    assert [beat.duration for beat in rhythm.beats] == ["quarter"] * 4
    assert not rhythm.abstains


def test_dotted_quarter_and_flagged_eighth_are_ok() -> None:
    rhythm = _read([{"kind": "note", "dots": 1}, {"kind": "note", "beams": 1}], expected_ticks=16)

    assert rhythm.status == "ok"
    assert rhythm.ticks == 16
    assert [beat.duration for beat in rhythm.beats] == ["quarter", "eighth"]
    assert rhythm.beats[0].dots == 1


def test_sum_mismatch_abstains_instead_of_guessing() -> None:
    """三拍拼不成 4/4：整小节 abstain（AR-05），不许调时值去凑。"""
    rhythm = _read([{"kind": "note"}] * 3, expected_ticks=32)

    assert rhythm.status == "unknown"
    assert rhythm.abstains
    assert rhythm.abstains[0].reason == "AR-05"
    assert rhythm.abstains[0].detail["items"][0]["expected"] == 32


def test_missing_time_signature_abstains() -> None:
    rhythm = _read([{"kind": "note"}] * 4, expected_ticks=None)

    assert rhythm.status == "unknown"
    assert rhythm.abstains[0].reason == "AR-09"


def test_empty_measure_is_a_whole_rest() -> None:
    arr = np.full((144, 200), 255, dtype=np.uint8)
    for line in range(5):
        arr[60 + line * DEG : 61 + line * DEG, 10:190] = 0
    system = _system(arr, staff_top=60)
    box = MeasureBox(index=1, printed=None, x0=10.0, x1=190.0, width=180.0)
    rhythm = read_measure(arr, system, box, DEG, expected_ticks=32)

    assert rhythm.status == "ok"
    assert rhythm.beats[0].kind == "rest"
    assert rhythm.beats[0].duration == "whole"


def test_staff_band_stops_above_the_tab_band() -> None:
    arr, (note_top, note_bottom, tab_top, _tab_bottom) = one_system_page()
    system = _system(arr, staff_top=note_top)
    system = system.model_copy(update={"tabY0": float(tab_top), "tabY1": float(tab_top + 54)})

    top, bottom = staff_band(system, DEG)

    assert top == note_top - 4 * DEG
    assert bottom < tab_top
    assert bottom >= note_bottom + 2 * DEG  # 符干与横梁要有余量


def test_staff_lines_are_erased_by_whole_thickness() -> None:
    """谱线 3 px 厚时，抹线必须把它整条抹掉（SR-11）。"""
    arr, (note_top, _note_bottom, tab_top, tab_bottom) = one_system_page()
    thick = np.full_like(arr, 255)
    for y in range(0, arr.shape[0] - 3):
        if y in {note_top + 4 * DEG * k for k in range(5)} or y in {
            tab_top + 18 * k for k in range(4)
        }:
            thick[y : y + 3, 60:1540] = 0
    system = _system(thick, staff_top=note_top)
    system = system.model_copy(update={"tabY0": float(tab_top), "tabY1": float(tab_bottom)})
    box = MeasureBox(index=1, printed=None, x0=60.0, x1=1540.0, width=1480.0)

    ctx = measure_context(thick, system, box, DEG)

    for row in ctx.line_rows:
        for delta in (-1, 0, 1):
            assert not ctx.beam_dark[row + delta, :].any(), f"第 {row + delta} 行没抹干净"


def test_four_beamed_eighths_are_ok() -> None:
    rhythm = _read([{"kind": "note", "beams": 1}] * 4, expected_ticks=16)

    assert rhythm.status == "ok"
    assert [beat.duration for beat in rhythm.beats] == ["eighth"] * 4


def test_whole_note_is_judged_as_whole() -> None:
    """全音符：空心头、无符干（SR-50）。任务 2 补上符头判据后它应该判得出来。"""
    rhythm = _read([{"kind": "whole"}], expected_ticks=32)

    assert rhythm.status == "ok"
    assert [beat.duration for beat in rhythm.beats] == ["whole"]
    assert rhythm.beats[0].head == "hollow"


def test_boundary_barline_is_not_counted_as_a_stem() -> None:
    """窗口左右外扩后，小节线会整个落在窗口里；它不能被当成一根没有符头的符干（SR-14）。"""
    arr = rhythm_measure([{"kind": "note"}] * 4, deg=DEG)
    width = arr.shape[1]
    system = System(
        id=1, page=0, y0=60.0, y1=60.0 + 4 * DEG, tabY0=0.0, tabY1=0.0,
        tabLines=[], measures=[], headerX0=0.0, headerX1=float(width),
    )
    box = MeasureBox(index=1, printed=None, x0=float(DEG), x1=float(width - DEG),
                     width=float(width - 2 * DEG))

    rhythm = read_measure(arr, system, box, DEG, expected_ticks=32)

    assert rhythm.status == "ok"
    assert [beat.duration for beat in rhythm.beats] == ["quarter"] * 4
