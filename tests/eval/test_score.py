"""打分器的测试（规格 §2.9、计划任务 14）。"""

from __future__ import annotations

import pytest

from aiaomr.eval.score import EvalError, measure, selftest
from aiaomr.eval.score import _perfect


def test_selftest_passes() -> None:
    selftest()


def test_perfect_answer_scores_one() -> None:
    ir, truth = _perfect()
    metrics = measure(ir, truth)

    assert {name: metric.value for name, metric in metrics.items()} == {
        "alignment": 1.0, "string_fret": 1.0, "pitch_exact": 1.0, "bars_add_up": 1.0
    }
    for metric in metrics.values():
        assert metric.total > 0


def test_deleted_note_lowers_note_metrics() -> None:
    ir, truth = _perfect()
    ir.measures[0].beats.pop()

    metrics = measure(ir, truth)

    assert metrics["string_fret"].value < 1.0
    assert metrics["string_fret"].total == 4


def test_wrong_fret_lowers_string_fret() -> None:
    ir, truth = _perfect()
    ir.measures[0].beats[0].notes[0].fret = 1
    ir.measures[0].beats[0].notes[0].pitch = 34

    metrics = measure(ir, truth)

    assert metrics["string_fret"].value < 1.0
    assert metrics["pitch_exact"].value < 1.0


def test_changed_duration_lowers_bars_add_up() -> None:
    ir, truth = _perfect()
    ir.measures[0].beats[0].duration = "eighth"

    metrics = measure(ir, truth)

    assert metrics["bars_add_up"].value < 1.0


def test_denominators_are_reported() -> None:
    ir, truth = _perfect()
    metrics = measure(ir, truth, max_measures=1)

    assert metrics["alignment"].total == 1
    assert metrics["string_fret"].total == 4
    assert metrics["bars_add_up"].total == len(ir.measures)
