"""验算层的测试（规格 §6.1 A1–A5、§2.5 F-03/F-04；计划任务 9）。"""

from __future__ import annotations

from aiaomr.kernel.contracts import MeasureRead, Skeleton
from aiaomr.kernel.ir import Beat, Evidence, Note, SkeletonProvenance, TimeSignature
from aiaomr.score.verify.invariants import check_all

EVIDENCE = Evidence(system=1, crop=[0, 0, 10, 10], call="c1")


def skeleton(*signatures: TimeSignature) -> Skeleton:
    return Skeleton(
        timeSignatures=list(signatures) or [TimeSignature(measure=1, beats=4, beatType=4)],
        keySignatures=[],
        tempos=[],
        tuning=[28, 33, 38, 43],
        stringCount=4,
        title="",
        artist="",
        provenance=SkeletonProvenance(
            timeSignatures="read",
            tuning="read",
            keySignatures="defaulted",
            tempos="defaulted",
            title="filename",
            artist="empty",
        ),
    )


def note(string: int = 1, fret: int = 0, digit: str | None = "0",
         pitch_claim: int | None = None, tie_fp: bool = False) -> Note:
    return Note(
        string=string,
        fret=fret,
        tie=False,
        tieFromPrevious=tie_fp,
        digit=None if digit is None else {"value": digit, "glyphs": len(digit), "bound": True},
        techniques=[],
        pitch=28 + fret,
        pitchClaim=pitch_claim,
    )


def beat(duration: str = "quarter", dots: int = 0, notes: list[Note] | None = None,
         rest: bool = False) -> Beat:
    return Beat(
        duration=duration,
        dots=dots,
        rest=rest,
        notes=notes or [],
        prov="read",
        evidence=EVIDENCE,
    )


def read(index: int, beats: list[Beat]) -> MeasureRead:
    return MeasureRead(index=index, beats=beats, unreadable=False)


def bar(index: int, notes: list[Note]) -> MeasureRead:
    """一整小节 4/4：第一拍放被测音符，其余三拍用 rest 补齐，避免 A1 干扰。"""
    return read(index, [beat(notes=notes)] + [beat(rest=True) for _ in range(3)])


def test_bar_duration_matches_time_signature() -> None:
    ok = read(1, [beat() for _ in range(4)])
    bad = read(2, [beat() for _ in range(3)])

    alarms = check_all([ok], skeleton())

    assert alarms == []
    alarms = check_all([bad], skeleton())
    assert [alarm.rule for alarm in alarms] == ["A1"]
    assert alarms[0].claimed == 24 and alarms[0].expected == 32


def test_bar_duration_uses_effective_time_signature() -> None:
    """中途换拍后，后面的小节按新拍号检查（A11 的基础）。"""
    skel = skeleton(TimeSignature(measure=1, beats=4, beatType=4),
                    TimeSignature(measure=3, beats=2, beatType=4))
    bars = [read(1, [beat() for _ in range(4)]), read(2, [beat() for _ in range(4)]),
            read(3, [beat() for _ in range(2)])]

    assert check_all(bars, skel) == []


def test_pitch_identity() -> None:
    good = bar(1, [note(string=4, fret=2, pitch_claim=45)])
    bad = bar(1, [note(string=4, fret=2, pitch_claim=44)])

    assert check_all([good], skeleton()) == []
    alarms = check_all([bad], skeleton())
    assert [alarm.rule for alarm in alarms] == ["A2"]


def test_fret_out_of_range() -> None:
    alarms = check_all([bar(1, [note(fret=25)])], skeleton())

    assert [alarm.rule for alarm in alarms] == ["A3"]


def test_digit_glyph_asymmetry_does_not_alarm() -> None:
    """七个数字、十三个字形、七个音符：正常 TAB 写法，不许报警（评审重点第三条）。"""
    digits = ["1", "2", "3", "4", "5", "6", "12"]
    notes = [note(string=2, fret=k, pitch_claim=33 + k, digit=digits[k]) for k in range(7)]
    reads = [bar(1, notes)]

    assert sum(len(note.digit.value) for note in notes) == 8  # 一个两位数
    assert check_all(reads, skeleton()) == []


def test_unexplained_notehead_without_digit_is_alarmed() -> None:
    reads = [bar(1, [note(digit=None, tie_fp=False)])]

    alarms = check_all(reads, skeleton())

    assert [alarm.rule for alarm in alarms] == ["A4b"]


def test_tuning_implied_by_pitch_claims() -> None:
    notes = [note(string=4, fret=k, pitch_claim=43 + k) for k in range(4)]
    ok = [bar(1, notes)]
    shift = [bar(1, [note(string=4, fret=k, pitch_claim=43 + k + 2) for k in range(4)])]

    assert check_all(ok, skeleton()) == []
    alarms = check_all(shift, skeleton())
    assert "A5" in [alarm.rule for alarm in alarms]
