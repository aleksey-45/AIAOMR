"""拍格与三条否决的测试（`docs/spec-staff.md` §8，SR-60..62）。"""

from __future__ import annotations

from aiaomr.kernel.contracts import RhythmBeat
from aiaomr.kernel.ir import TimeSignature
from aiaomr.score.staff.organize import beat_group_ticks, organize


def ts(beats: int, beat_type: int = 4) -> TimeSignature:
    return TimeSignature(measure=1, beats=beats, beatType=beat_type)


def beat(duration: str, group: int | None = None, dots: int = 0) -> RhythmBeat:
    return RhythmBeat(x=0.0, kind="note", duration=duration, dots=dots, group=group)


def test_beat_group_ticks_follows_time_signature() -> None:
    assert beat_group_ticks(ts(4)) == 8
    assert beat_group_ticks(ts(3)) == 8
    assert beat_group_ticks(ts(2)) == 8
    assert beat_group_ticks(ts(6, 8)) == 12
    assert beat_group_ticks(ts(9, 8)) == 12
    assert beat_group_ticks(ts(12, 8)) == 12
    assert beat_group_ticks(ts(2, 2)) == 16
    assert beat_group_ticks(ts(5, 8)) is None


def test_four_quarters_fill_the_bar() -> None:
    result = organize([beat("quarter") for _ in range(4)], signature=ts(4))

    assert result.status == "ok"
    assert result.ticks == 32


def test_sum_mismatch_is_rejected_not_adjusted() -> None:
    result = organize([beat("quarter") for _ in range(3)], signature=ts(4))

    assert result.status == "unknown"
    assert any(reason == "AR-05" for reason, _detail in result.abstains)


def test_beam_group_must_end_on_a_beat_group() -> None:
    """4/4 里三个八分连成一组（12 tick）不是整拍组，必须否决（SR-60）。"""
    result = organize([beat("eighth", group=1) for _ in range(3)], signature=ts(4))

    assert result.status == "unknown"
    assert any(reason == "AR-04" for reason, _detail in result.abstains)


def test_two_eighths_group_on_one_beat_is_fine() -> None:
    beats = [beat("eighth", group=1), beat("eighth", group=1)] + [
        beat("quarter") for _ in range(3)
    ]

    result = organize(beats, signature=ts(4))

    assert result.status == "ok"


def test_three_eighths_groups_are_fine_in_six_eight() -> None:
    """6/8 一小节是两组三连八分（每组的拍组是附点四分 = 12 tick）。"""
    beats = [beat("eighth", group=1) for _ in range(3)] + [
        beat("eighth", group=2) for _ in range(3)
    ]

    result = organize(beats, signature=ts(6, 8))

    assert result.status == "ok"
    assert result.ticks == 24


def test_missing_signature_abstains() -> None:
    result = organize([beat("quarter")], signature=None, expected=None)

    assert result.status == "unknown"
    assert result.abstains[0][0] == "AR-09"


def test_unknown_duration_abstains() -> None:
    result = organize([beat(None), beat("half")], signature=ts(4))

    assert result.status == "unknown"
    assert any(reason == "AR-02" for reason, _detail in result.abstains)


def test_single_note_may_start_off_the_beat() -> None:
    """单个音符不是连梁组，可以落在任何合法拍位上（附点四分从第三拍后半开始很正常）。"""
    beats = [beat("half"), beat("eighth"), beat("quarter", dots=1)]

    result = organize(beats, signature=ts(4))

    assert result.status == "ok"
    assert result.ticks == 32
