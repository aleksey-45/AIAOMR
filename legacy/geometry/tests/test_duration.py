"""时值判定表的测试（`docs/spec-staff.md` SR-50..57）。"""

from __future__ import annotations

from aiaomr.score.staff.duration import note_duration, rest_duration, ticks


def test_hollow_head_without_stem_is_whole() -> None:
    assert note_duration("hollow", has_stem=False, beams=0) == "whole"


def test_hollow_head_with_stem_is_half() -> None:
    assert note_duration("hollow", has_stem=True, beams=0) == "half"
    # 空心符头不会被横梁条数影响（二分音符不与八分连梁，见 SR-24）
    assert note_duration("hollow", has_stem=True, beams=1) == "half"


def test_filled_head_duration_follows_beam_count() -> None:
    assert note_duration("filled", has_stem=True, beams=0) == "quarter"
    assert note_duration("filled", has_stem=True, beams=1) == "eighth"
    assert note_duration("filled", has_stem=True, beams=2) == "16th"
    assert note_duration("filled", has_stem=True, beams=3) == "32nd"


def test_filled_head_without_stem_is_unknown() -> None:
    assert note_duration("filled", has_stem=False, beams=0) is None


def test_missing_head_class_is_unknown() -> None:
    assert note_duration(None, has_stem=True, beams=1) is None


def test_rest_categories_map_to_durations() -> None:
    assert rest_duration("rest_whole") == "whole"
    assert rest_duration("rest_half") == "half"
    assert rest_duration("rest_quarter") == "quarter"
    assert rest_duration("rest_eighth") == "eighth"
    assert rest_duration("bogus") is None


def test_dots_multiply_ticks() -> None:
    assert ticks("quarter") == 8
    assert ticks("quarter", 1) == 12
    assert ticks("quarter", 2) == 14
    assert ticks("half", 1) == 24
    assert ticks(None) is None
