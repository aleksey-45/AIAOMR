"""附点判据真图验收（计划任务 2；`docs/spec-staff.md` SR-33..36）。

- 音符附点锚在**符头右侧**（不再锚符干底部，SR-33）；
- 休止符的附点按同一判据锚在休止字形右侧，`evidence["anchor"]` 要写清是 head 还是 rest（SR-36）；
- 断音点画在符头另一侧，必须排除（SR-35）；双附点（两个点都在右侧）要能都报出来（SR-34）。
"""

from __future__ import annotations

import numpy as np

from aiaomr.kernel.contracts import MeasureBox, System
from aiaomr.score.staff.context import measure_context
from aiaomr.score.staff.dots import DotCriterion
from tests.fixtures.rhythm_pages import _disc, rhythm_measure

DEG = 12


def _samples(manifest: dict, *classes: str) -> list[dict]:
    return [sample for sample in manifest["samples"] if sample["class"] in classes]


def _context(beats: list[dict], extra=None):
    arr = rhythm_measure(beats, deg=DEG)
    if extra is not None:
        extra(arr)
    width = arr.shape[1]
    system = System(id=1, page=0, y0=60.0, y1=60.0 + 4 * DEG, tabY0=0.0, tabY1=0.0,
                    tabLines=[], measures=[], headerX0=0.0, headerX1=float(width))
    box = MeasureBox(index=1, printed=None, x0=float(DEG), x1=float(width - DEG),
                     width=float(width - 2 * DEG))
    return measure_context(arr, system, box, DEG)


def _note_positions(count: int) -> list[float]:
    gap = 3.0 * DEG
    width = int(DEG + gap * count + DEG)
    return [DEG + gap * (index + 0.6) for index in range(count)], width


# ---------------------------------------------------------------- 真图样本


def test_dot_on_note_is_right_of_head(manifest, context_for, staff_config) -> None:
    samples = _samples(manifest, "dot_on_note")
    assert samples
    for sample in samples:
        dots = DotCriterion(staff_config).detect(context_for(sample), {})
        assert dots, f"{sample['file']} 没找到附点"
        for dot in dots:
            assert dot.evidence["anchor"] == "head"
            anchor = dot.evidence["anchor_bbox"]
            head_center_x = (anchor[0] + anchor[2]) / 2
            dot_center_x = (dot.bbox[0] + dot.bbox[2]) / 2
            assert dot_center_x > head_center_x, f"{sample['file']} 附点不在符头右侧"


def test_dot_on_rest_is_anchored_on_rest(manifest, context_for, staff_config) -> None:
    samples = _samples(manifest, "dot_on_rest")
    assert samples
    for sample in samples:
        dots = DotCriterion(staff_config).detect(context_for(sample), {})
        assert dots, f"{sample['file']} 没找到休止符附点"
        assert any(dot.evidence["anchor"] == "rest" for dot in dots), f"{sample['file']} 锚点不是休止符"
        for dot in dots:
            anchor = dot.evidence["anchor_bbox"]
            dot_center_x = (dot.bbox[0] + dot.bbox[2]) / 2
            assert dot_center_x > (anchor[0] + anchor[2]) / 2


def test_dot_detection_is_deterministic(manifest, context_for, staff_config) -> None:
    for sample in _samples(manifest, "dot_on_note", "dot_on_rest"):
        ctx = context_for(sample)
        first = [(dot.value, dot.bbox, dict(dot.evidence)) for dot in DotCriterion(staff_config).detect(ctx, {})]
        second = [(dot.value, dot.bbox, dict(dot.evidence)) for dot in DotCriterion(staff_config).detect(ctx, {})]
        assert first == second


# ---------------------------------------------------------------- 合成反例


def test_staccato_dot_on_the_other_side_is_excluded(staff_config) -> None:
    """断音点画在符头另一侧（左侧/上方）；只认右侧附点，所以它不能被算成时值附点。"""
    positions, _width = _note_positions(1)

    def draw_left_dot(arr: np.ndarray) -> None:
        note_y = 60 + 3 * DEG
        _disc(arr, positions[0] - 1.2 * DEG, note_y - 0.5 * DEG, 0.16 * DEG, 0.16 * DEG)

    ctx = _context([{"kind": "note"}], extra=draw_left_dot)
    dots = DotCriterion(staff_config).detect(ctx, {})

    assert not dots, "符头左侧的断音点被当成了附点"


def test_double_dot_is_reported_as_two(staff_config) -> None:
    """双附点：两个点都在右侧，第一个 1.25·deg、第二个再往右 ~0.85·deg（SR-34）。"""
    positions, _width = _note_positions(2)

    def draw_two_dots(arr: np.ndarray) -> None:
        note_y = 60 + 3 * DEG
        _disc(arr, positions[0] + 1.25 * DEG, note_y - 0.55 * DEG, 0.16 * DEG, 0.16 * DEG)
        _disc(arr, positions[0] + 2.1 * DEG, note_y - 0.55 * DEG, 0.16 * DEG, 0.16 * DEG)

    ctx = _context([{"kind": "note"}, {"kind": "note"}], extra=draw_two_dots)
    dots = DotCriterion(staff_config).detect(ctx, {})

    assert dots
    assert max(dot.evidence["dots"] for dot in dots) == 2
    assert min(dot.evidence["index"] for dot in dots) == 1
    assert max(dot.evidence["index"] for dot in dots) == 2
