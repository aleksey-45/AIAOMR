"""`tools/review/compare_tab.py` 的对齐与统计单测（离线、纯合成数据）。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "review" / "compare_tab.py"


def _module():
    spec = importlib.util.spec_from_file_location("compare_tab_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(index: int, notes=(), *, rest: bool = False):
    beats = []
    if rest:
        beats = [{"duration": "whole", "rest": True, "notes": []}]
    else:
        for string, fret in notes:
            beats.append({"duration": "quarter", "rest": False,
                          "notes": [{"string": string, "fret": fret}]})
    return {"index": index, "beats": beats}


def _truth(index: int, notes=(), *, rest: bool = False):
    beats = []
    if rest:
        beats = [{"ticks": 3840, "rest": True, "notes": []}]
    else:
        for string, fret in notes:
            beats.append({"ticks": 960, "rest": False,
                          "notes": [{"string": string, "fret": fret}]})
    return {"index": index, "beats": beats}


def test_identical_measures_are_exact() -> None:
    module = _module()
    reads = [_read(1, [(2, 6)]), _read(2, [(1, 3)])]
    truth = [_truth(1, [(2, 6)]), _truth(2, [(1, 3)])]

    report = module.compare(reads, truth)

    assert report["tabCompared"] == 2
    assert report["tabExact"] == 2
    assert report["fretExact"] == 2
    assert report["mismatches"] == []


def test_string_assignment_errors_are_counted_separately_from_frets() -> None:
    """弦号错、品数对：TAB 不算对，但"只比品数"应该算对（这是现在最需要盯的指标）。"""
    module = _module()
    reads = [_read(1, [(1, 6), (2, 8)])]
    truth = [_truth(1, [(2, 6), (4, 8)])]

    report = module.compare(reads, truth)

    assert report["tabCompared"] == 1
    assert report["tabExact"] == 0
    assert report["fretExact"] == 1
    assert report["mismatches"][0]["extra"] == [[1, 6], [2, 8]]


def test_multirest_bar_aligns_to_a_block_of_rest_measures() -> None:
    """谱面上一条全休止条只显示一个小节，真值里是连续多个休止小节。"""
    module = _module()
    reads = [_read(1, rest=True), _read(2, [(2, 6)])]
    truth = [_truth(1, rest=True), _truth(2, rest=True), _truth(3, rest=True), _truth(4, [(2, 6)])]

    pairs = module.align(reads, truth)
    report = module.compare(reads, truth)

    # 休止条对准哪一个小节不是重点，重点是：音乐小节对上了、两个多出来的休止小节被标成展开
    assert pairs[-1] == (1, 3)
    assert report["tabCompared"] == 1 and report["tabExact"] == 1
    assert len(report["unmatchedRest"]) == 2
    assert report["missingNonRest"] == []


def test_unreadable_bar_is_not_counted_as_correct() -> None:
    module = _module()
    reads = [{"index": 1, "beats": [], "unreadable": True}, _read(2, [(1, 3)])]
    truth = [_truth(1, [(2, 6)]), _truth(2, [(1, 3)])]

    report = module.compare(reads, truth)

    assert report["tabExact"] == 1
    assert report["tabCompared"] == 1
