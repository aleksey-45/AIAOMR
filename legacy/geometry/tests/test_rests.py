"""休止符三组判据真图验收（计划任务 2；`docs/spec-staff.md` SR-37..39b）。

硬门：**二分休止判成四分休止必须为零**（时值差 2 倍、旧项目失败最多的一类）。
全休止 / 二分休止只靠挂线位置区分，不许按高度猜。
"""

from __future__ import annotations

import numpy as np

from aiaomr.kernel.contracts import MeasureBox, System
from aiaomr.score.staff.context import measure_context
from aiaomr.score.staff.rests import (
    REST_TICKS,
    RestBarCriterion,
    RestGlyphCriterion,
    RestRectCriterion,
)

DEG = 12


def _samples(manifest: dict, *classes: str) -> list[dict]:
    return [sample for sample in manifest["samples"] if sample["class"] in classes]


def _categories(findings) -> list[str]:
    return [finding.evidence["category"] for finding in findings]


# ---------------------------------------------------------------- 全休止 / 二分休止


def test_whole_rest_fixture_is_whole(manifest, context_for, staff_config) -> None:
    for sample in _samples(manifest, "rest_whole"):
        findings = RestRectCriterion(staff_config).detect(context_for(sample))
        assert _categories(findings) == ["rest_whole"], f"{sample['file']} 判成 {_categories(findings)}"
        assert findings[0].value == REST_TICKS["whole"]
        assert findings[0].evidence["attach"] == "below_line"


def test_half_rest_fixtures_are_half(manifest, context_for, staff_config) -> None:
    samples = _samples(manifest, "rest_half")
    assert samples
    for sample in samples:
        findings = RestRectCriterion(staff_config).detect(context_for(sample))
        assert _categories(findings) == ["rest_half"], f"{sample['file']} 判成 {_categories(findings)}"
        assert findings[0].value == REST_TICKS["half"]
        assert findings[0].evidence["attach"] == "on_line"


def test_half_rest_is_not_judged_as_quarter(manifest, context_for, staff_config) -> None:
    """硬门：二分休止不许被当成四分休止（那条字形判据也不许冒出来）。"""
    for sample in _samples(manifest, "rest_half"):
        ctx = context_for(sample)
        glyphs = RestGlyphCriterion(staff_config).detect(ctx)
        assert "rest_quarter" not in _categories(glyphs), f"{sample['file']} 把二分休止判成了四分"
        rects = RestRectCriterion(staff_config).detect(ctx)
        assert "rest_whole" not in _categories(rects), f"{sample['file']} 把二分休止判成了全休止"


# ---------------------------------------------------------------- 四分 / 八分休止


def test_quarter_rest_fixtures_are_quarter(manifest, context_for, staff_config) -> None:
    samples = _samples(manifest, "rest_quarter")
    assert samples
    for sample in samples:
        findings = RestGlyphCriterion(staff_config).detect(context_for(sample))
        assert _categories(findings) == ["rest_quarter"], f"{sample['file']} 判成 {_categories(findings)}"
        assert findings[0].value == REST_TICKS["quarter"]


def test_eighth_rest_fixtures_are_eighth(manifest, context_for, staff_config) -> None:
    samples = _samples(manifest, "rest_eighth")
    assert samples
    for sample in samples:
        findings = RestGlyphCriterion(staff_config).detect(context_for(sample))
        assert _categories(findings) == ["rest_eighth"], f"{sample['file']} 判成 {_categories(findings)}"
        assert findings[0].value == REST_TICKS["eighth"]


def test_quarter_rest_is_not_judged_as_eighth(manifest, context_for, staff_config) -> None:
    for sample in _samples(manifest, "rest_quarter"):
        categories = _categories(RestGlyphCriterion(staff_config).detect(context_for(sample)))
        assert "rest_eighth" not in categories


# ---------------------------------------------------------------- 多小节休止条


def test_multirest_bar_still_detected(staff_config) -> None:
    arr = np.full((120, 200), 255, dtype=np.uint8)
    for line in range(5):
        arr[40 + line * DEG : 41 + line * DEG, 10:190] = 0
    arr[76:86, 10:190] = 0  # 贯穿小节宽度的粗横线
    system = System(id=1, page=0, y0=40.0, y1=40.0 + 4 * DEG, tabY0=0.0, tabY1=0.0,
                    tabLines=[], measures=[], headerX0=0.0, headerX1=200.0)
    box = MeasureBox(index=1, printed=None, x0=10.0, x1=190.0, width=180.0)
    ctx = measure_context(arr, system, box, DEG)

    findings = RestBarCriterion().detect(ctx)
    assert findings
    assert findings[0].evidence["category"] == "rest_bar"


# ---------------------------------------------------------------- 确定性


def test_rest_detection_is_deterministic(manifest, context_for, staff_config) -> None:
    for sample in _samples(manifest, "rest_whole", "rest_half", "rest_quarter", "rest_eighth"):
        ctx = context_for(sample)
        first = [
            (finding.kind, finding.value, finding.bbox, dict(finding.evidence))
            for finding in RestRectCriterion(staff_config).detect(ctx)
            + RestGlyphCriterion(staff_config).detect(ctx)
        ]
        second = [
            (finding.kind, finding.value, finding.bbox, dict(finding.evidence))
            for finding in RestRectCriterion(staff_config).detect(ctx)
            + RestGlyphCriterion(staff_config).detect(ctx)
        ]
        assert first == second
