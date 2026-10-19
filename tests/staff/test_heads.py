"""符头判据真图验收（计划任务 2；`docs/spec-staff.md` SR-20..24）。

硬门（旧项目失败最多的一类）：
- **实心判成空心、空心判成实心，两种组合必须为零**；
- 三类连梁样本里的符头类别必须是实心。
"""

from __future__ import annotations

import numpy as np
import pytest

from aiaomr.score.staff.heads import HeadCriterion
from aiaomr.score.staff.templates import HeadTemplates, normalize

HOLLOW_CLASSES = ("hollow_no_stem", "hollow_stem")
FILLED_CLASSES = ("filled_stem", "beamed_1", "beamed_2")
HEAD_CLASSES = HOLLOW_CLASSES + FILLED_CLASSES


def _samples(manifest: dict, classes) -> list[dict]:
    return [sample for sample in manifest["samples"] if sample["class"] in classes]


def _label(finding) -> str:
    return "hollow" if finding.value == 1.0 else "filled"


def _detect(sample, context_for, staff_config):
    return HeadCriterion(staff_config).detect(context_for(sample))


def test_every_head_fixture_produces_at_least_one_head(manifest, context_for, staff_config) -> None:
    for sample in _samples(manifest, HEAD_CLASSES):
        heads = _detect(sample, context_for, staff_config)
        assert heads, f"{sample['file']} 一颗符头都没找到"


def test_hollow_fixtures_are_hollow(manifest, context_for, staff_config) -> None:
    for sample in _samples(manifest, HOLLOW_CLASSES):
        heads = _detect(sample, context_for, staff_config)
        assert all(_label(head) == "hollow" for head in heads), (
            f"{sample['file']} 期望空心，判成 {[_label(h) for h in heads]}"
        )


def test_filled_fixtures_are_filled(manifest, context_for, staff_config) -> None:
    for sample in _samples(manifest, FILLED_CLASSES):
        heads = _detect(sample, context_for, staff_config)
        assert all(_label(head) == "filled" for head in heads), (
            f"{sample['file']} 期望实心，判成 {[_label(h) for h in heads]}"
        )


def test_beamed_head_fixtures_are_filled(manifest, context_for, staff_config) -> None:
    """SR-24：一个连梁组里的符头都是实心；连梁样本里不许出现空心结论。"""
    for sample in _samples(manifest, ("beamed_1", "beamed_2")):
        heads = _detect(sample, context_for, staff_config)
        assert heads, f"{sample['file']} 连梁组没找到符头"
        assert all(_label(head) == "filled" for head in heads)


def test_confusion_table_has_no_hollow_filled_mixups(manifest, context_for, staff_config) -> None:
    """按样本类别汇总混淆表；实心↔空心互换必须为零（硬门）。"""
    table: dict[tuple[str, str], int] = {}
    for sample in _samples(manifest, HEAD_CLASSES):
        expected = "hollow" if sample["class"] in HOLLOW_CLASSES else "filled"
        heads = _detect(sample, context_for, staff_config)
        predicted = "none"
        labels = {_label(head) for head in heads}
        if len(labels) == 1:
            predicted = labels.pop()
        elif len(labels) > 1:
            predicted = "mixed"
        table[(expected, predicted)] = table.get((expected, predicted), 0) + 1

    swapped = sum(
        count for (expected, predicted), count in table.items()
        if {expected, predicted} == {"hollow", "filled"}
    )
    assert swapped == 0, f"实心/空心互换：{table}"
    assert table.get(("hollow", "mixed"), 0) == 0, f"空心样本里混进了实心结论：{table}"
    assert table.get(("filled", "mixed"), 0) == 0, f"实心样本里混进了空心结论：{table}"
    assert table.get(("hollow", "none"), 0) == 0, f"空心样本漏判：{table}"
    assert table.get(("filled", "none"), 0) == 0, f"实心样本漏判：{table}"


def test_head_boxes_stay_inside_configured_ranges(manifest, context_for, staff_config) -> None:
    for sample in _samples(manifest, HEAD_CLASSES):
        ctx = context_for(sample)
        deg = ctx.deg
        for head in _detect(sample, context_for, staff_config):
            width = head.bbox[2] - head.bbox[0]
            height = head.bbox[3] - head.bbox[1]
            assert staff_config.head_w_deg[0] * deg <= width <= staff_config.head_w_deg[1] * deg
            assert staff_config.head_h_deg[0] * deg <= height <= staff_config.head_h_deg[1] * deg
            assert width / height >= 1.1


def test_hole_count_is_only_evidence(manifest, context_for, staff_config) -> None:
    """SR-23：洞判据只当佐证写进 evidence，不参与类别结论（真图上谱线会把洞切开）。"""
    sample = _samples(manifest, ("hollow_stem",))[0]
    heads = _detect(sample, context_for, staff_config)
    assert heads
    for head in heads:
        assert "holes" in head.evidence
        assert "fill" in head.evidence


def test_detection_is_deterministic(manifest, context_for, staff_config) -> None:
    for sample in _samples(manifest, HEAD_CLASSES):
        ctx = context_for(sample)
        first = [(h.value, h.bbox, dict(h.evidence)) for h in HeadCriterion(staff_config).detect(ctx)]
        second = [(h.value, h.bbox, dict(h.evidence)) for h in HeadCriterion(staff_config).detect(ctx)]
        assert first == second, f"{sample['file']} 两次判定不一致"


def test_conflicting_fill_jumps_to_abstain(manifest, context_for, staff_config) -> None:
    """填充率与几何结论矛盾、模板又自举不出来时，不许硬选，直接不产出 Finding（AR-02）。"""
    import dataclasses

    conflicted = dataclasses.replace(staff_config, head_fill_hollow_max=0.99, head_fill_filled_min=0.99)
    sample = _samples(manifest, ("filled_stem",))[0]
    heads = HeadCriterion(conflicted).detect(context_for(sample))
    assert heads == [], "填充率和几何结论矛盾时不该产出 Finding"


# ---------------------------------------------------------------- 模板自举（SR-22）


def _patch(kind: str, rx: float = 8.0, ry: float = 5.0) -> np.ndarray:
    """画一张归一化前的候选墨迹：空心环 / 实心椭圆。"""
    canvas = np.zeros((16, 20), np.uint8)
    ys, xs = np.mgrid[0:16, 0:20]
    cx, cy = 10.0, 8.0
    outer = ((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2 <= 1.0
    if kind == "filled":
        canvas[outer] = 255
    else:
        inner = ((xs - cx) / max(1.0, rx - 2.5)) ** 2 + ((ys - cy) / max(1.0, ry - 2.0)) ** 2 <= 1.0
        canvas[outer & ~inner] = 255
    return canvas


def test_templates_bootstrap_from_both_classes_and_classify() -> None:
    filled = [normalize(_patch("filled", rx, ry)) for rx, ry in ((8.0, 5.0), (7.0, 4.5), (9.0, 5.5))]
    hollow = [normalize(_patch("hollow", rx, ry)) for rx, ry in ((8.0, 5.0), (7.0, 4.5), (9.0, 5.5))]
    templates = HeadTemplates.bootstrap({"filled": filled, "hollow": hollow})

    assert templates is not None
    assert templates.labels == ("filled", "hollow")
    filled_result = templates.classify(_patch("filled"), ncc_min=0.5)
    hollow_result = templates.classify(_patch("hollow"), ncc_min=0.5)
    assert filled_result is not None and filled_result[0] == "filled"
    assert hollow_result is not None and hollow_result[0] == "hollow"


def test_templates_need_both_classes() -> None:
    only_filled = [normalize(_patch("filled")) for _ in range(3)]
    assert HeadTemplates.bootstrap({"filled": only_filled, "hollow": []}) is None


def test_templates_are_deterministic() -> None:
    patches = {"filled": [normalize(_patch("filled", rx)) for rx in (7.0, 8.0, 9.0)],
               "hollow": [normalize(_patch("hollow", rx)) for rx in (7.0, 8.0, 9.0)]}
    first = HeadTemplates.bootstrap(patches)
    second = HeadTemplates.bootstrap(patches)
    assert first is not None and second is not None
    for label in first.labels:
        assert np.array_equal(first.templates[label], second.templates[label])
