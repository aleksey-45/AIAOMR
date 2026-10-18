"""打分器的测试（规格 §2.9 EV-01..04、§9.2 语料门、计划任务 14 与任务 0-D）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiaomr.eval.score import EvalError, load_truth, measure, selftest
from aiaomr.eval.score import _perfect

# 真值 JSON 里的 ticks 是 alphaTab 的 playbackDuration：四分音符 = 960，一小节 4/4 = 3840。
_BAR_4_4 = 3840


def _write_truth(tmp_path: Path, measures: list[dict]) -> Path:
    """写一份与 tools/dump.mjs 产物同形的真值文件。"""
    path = tmp_path / "truth.json"
    data = {
        "available": True,
        "title": "测试",
        "tuning": [28, 33, 38, 43],
        "measures": measures,
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _measure(index: int, beats: list[dict], numerator: int = 4, denominator: int = 4) -> dict:
    return {
        "index": index,
        "timeSignature": {"numerator": numerator, "denominator": denominator},
        "beats": beats,
    }


def _beat(ticks: int, rest: bool = False) -> dict:
    return {"ticks": ticks, "rest": rest, "notes": [] if rest else [{"string": 2, "fret": 2, "pitch": 35}]}


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


def test_load_truth_accepts_bar_that_adds_up(tmp_path: Path) -> None:
    path = _write_truth(
        tmp_path,
        [
            _measure(1, [_beat(1920), _beat(480), _beat(1440)]),
            _measure(2, [_beat(960), _beat(960), _beat(960), _beat(960)]),
        ],
    )

    truth = load_truth(path)

    assert [measure_obj["index"] for measure_obj in truth["measures"]] == [1, 2]
    assert truth["measures"][0]["beats"][0]["ticks"] == 1920
    assert truth["measures"][0]["timeSignature"] == {"numerator": 4, "denominator": 4}


def test_load_truth_uses_per_measure_time_signature(tmp_path: Path) -> None:
    # 中途换 3/4：期望时值按该小节自己的拍号算，不是全曲统一的 4/4。
    path = _write_truth(
        tmp_path,
        [
            _measure(1, [_beat(_BAR_4_4, rest=True)]),
            _measure(2, [_beat(1920), _beat(960)], numerator=3, denominator=4),
        ],
    )

    truth = load_truth(path)

    assert truth["measures"][1]["timeSignature"] == {"numerator": 3, "denominator": 4}


def test_load_truth_rejects_bar_with_extra_quarter_rests(tmp_path: Path) -> None:
    # 旧产物 out/p1/打上花火/truth.json 的样子：m17 多出三个四分休止（7 个四分 = 6720）。
    path = _write_truth(
        tmp_path,
        [
            _measure(
                17,
                [_beat(1920), _beat(480), _beat(1440), _beat(960, rest=True),
                 _beat(960, rest=True), _beat(960, rest=True)],
            )
        ],
    )

    with pytest.raises(EvalError) as caught:
        load_truth(path)

    message = str(caught.value)
    assert "第 17 小节" in message
    assert "3840" in message  # 4/4 应有的时值
    assert "6720" in message  # 实际加起来的时值


def test_load_truth_rejects_bar_without_beats(tmp_path: Path) -> None:
    path = _write_truth(tmp_path, [_measure(1, [])])

    with pytest.raises(EvalError) as caught:
        load_truth(path)

    assert "第 1 小节" in str(caught.value)


def test_load_truth_rejects_old_file_without_time_signature(tmp_path: Path) -> None:
    path = tmp_path / "truth.json"
    path.write_text(
        json.dumps(
            {
                "available": True,
                "title": "旧产物",
                "tuning": [28, 33, 38, 43],
                "measures": [{"index": 1, "beats": [_beat(960)] * 4}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(EvalError) as caught:
        load_truth(path)

    message = str(caught.value)
    assert "第 1 小节" in message
    assert "timeSignature" in message
    assert "重导" in message


def test_load_truth_rejects_mismatched_time_signature_total(tmp_path: Path) -> None:
    # 拍号写 3/4，实际塞了 4 个四分：必须按 2880 判，不能按 3840 判。
    path = _write_truth(
        tmp_path,
        [_measure(5, [_beat(960), _beat(960), _beat(960), _beat(960)], numerator=3, denominator=4)],
    )

    with pytest.raises(EvalError) as caught:
        load_truth(path)

    message = str(caught.value)
    assert "第 5 小节" in message
    assert "2880" in message
    assert "3840" in message


def test_dump_output_shape_is_loadable(tmp_path: Path) -> None:
    # 与 tools/dump.mjs 的产物同形：每小节带 index 与 timeSignature，beats 里是 ticks/rest/notes。
    path = _write_truth(
        tmp_path,
        [
            _measure(1, [_beat(1920), _beat(480), _beat(1440)]),
            _measure(2, [_beat(_BAR_4_4, rest=True)]),  # GP5 的空小节：整小节休止
        ],
    )

    truth = load_truth(path)

    assert set(truth) == {"available", "title", "tuning", "measures"}
    for measure_obj in truth["measures"]:
        assert set(measure_obj) == {"index", "timeSignature", "beats"}
        assert set(measure_obj["timeSignature"]) == {"numerator", "denominator"}
        for beat in measure_obj["beats"]:
            assert set(beat) == {"ticks", "rest", "notes"}
