"""GP5 写出的测试（规格 §4.3、E-01..E-04；计划任务 11 的四个用例）。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import guitarpro as gp
import pytest

from aiaomr.kernel.errors import ErrorCode
from aiaomr.kernel.ir import (
    Beat,
    Evidence,
    IR,
    Measure,
    Meta,
    Note,
    Score,
    SkeletonProvenance,
    Source,
    Structure,
    TimeSignature,
)
from aiaomr.writers.base import WriterError
from aiaomr.writers.gp5.writer import GP5Writer

EVIDENCE = Evidence(system=1, crop=[0, 0, 10, 10], call="c1")


def note(string: int = 1, fret: int = 3) -> Note:
    return Note(string=string, fret=fret, tie=False, tieFromPrevious=False,
                techniques=[], pitch=28 + fret, pitchClaim=None)


def beat(duration: str = "quarter", notes: list[Note] | None = None,
         dots: int = 0, rest: bool = False) -> Beat:
    return Beat(duration=duration, dots=dots, rest=rest, notes=notes or [],
                prov="read", evidence=EVIDENCE)


def measure(index: int, beats: list[Beat] | None = None, rest: bool = False) -> Measure:
    return Measure(index=index, printed=None, rest=rest, multiRest=1, beats=beats or [])


def make_ir(measures: list[Measure], title: str = "测试曲", *,
            signatures: list[TimeSignature] | None = None) -> IR:
    return IR(
        meta=Meta(provider="stub", model="stub", promptVersion="p0", schemaVersion="3.0",
                  generatedAt=datetime.now(timezone.utc)),
        source=Source(**{"class": 3}, kind="image", files=[], inputSha256=""),
        score=Score(
            title=title, artist="测试作者", tabber="", tuning=[28, 33, 38, 43], stringCount=4,
            timeSignatures=signatures or [TimeSignature(measure=1, beats=4, beatType=4)],
            keySignatures=[], tempos=[], clefTranspose=-12, fretCount=24,
        ),
        skeletonProvenance=SkeletonProvenance(
            timeSignatures="read", tuning="read", keySignatures="defaulted",
            tempos="defaulted", title="filename", artist="empty",
        ),
        measures=measures, structure=Structure(), judgements=[], build=None,
    )


def four_quarters(notes: list[Note] | None = None) -> list[Beat]:
    notes = notes or [note()]
    return [beat(notes=[notes[0]])] + [beat(notes=[note()]) for _ in range(3)]


def test_roundtrip_is_ok_and_notes_survive(tmp_path: Path) -> None:
    ir = make_ir([measure(1, beats=four_quarters()), measure(2, rest=True)])
    writer = GP5Writer()
    path = tmp_path / "out.gp5"

    report = writer.write(ir, str(path))

    assert report.roundtrip == "OK"
    assert report.measures == 2
    assert path.exists() and path.stat().st_size > 0
    song = gp.parse(str(path), encoding="cp936")
    assert song.title == "测试曲"
    assert len(song.tracks[0].measures) == 2
    played = song.tracks[0].measures[0].voices[0].beats
    assert len(played) == 4
    assert len(played[0].notes) == 1


def test_string_flip_happens_only_here(tmp_path: Path) -> None:
    """IR 第 1 弦 = 最低音弦；写进 gp5 后要变成第 4 弦 = 最高音弦。"""
    ir = make_ir([measure(1, beats=four_quarters([note(string=1, fret=7)]))])
    path = tmp_path / "flip.gp5"

    GP5Writer().write(ir, str(path))

    song = gp.parse(str(path), encoding="cp936")
    parsed = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    assert parsed.string == 4
    assert parsed.value == 7


def test_unknown_duration_is_rejected(tmp_path: Path) -> None:
    """dots=2 暂不支持（§4.3）：校验失败，且不许留下半个文件。"""
    beats = [beat(dots=2)] + [beat() for _ in range(3)]
    ir = make_ir([measure(1, beats=beats)])
    path = tmp_path / "bad.gp5"

    with pytest.raises(WriterError) as excinfo:
        GP5Writer().write(ir, str(path))

    assert excinfo.value.code is ErrorCode.E_BUILD_VALIDATE
    assert not path.exists()


def test_non_cp936_title_is_refused(tmp_path: Path) -> None:
    ir = make_ir([measure(1, beats=four_quarters())], title="吉他🎸")
    path = tmp_path / "cjk.gp5"

    with pytest.raises(WriterError) as excinfo:
        GP5Writer().write(ir, str(path))

    assert excinfo.value.code is ErrorCode.E_BUILD_VALIDATE
    assert not path.exists()


def test_bar_duration_mismatch_is_rejected(tmp_path: Path) -> None:
    ir = make_ir([measure(1, beats=[beat() for _ in range(3)])])
    path = tmp_path / "short.gp5"

    with pytest.raises(WriterError) as excinfo:
        GP5Writer().write(ir, str(path))

    assert excinfo.value.code is ErrorCode.E_BUILD_VALIDATE


def test_time_signature_change_is_written(tmp_path: Path) -> None:
    signatures = [TimeSignature(measure=1, beats=4, beatType=4),
                  TimeSignature(measure=2, beats=2, beatType=4)]
    ir = make_ir(
        [measure(1, beats=four_quarters()),
         measure(2, beats=[beat(notes=[note()]), beat(notes=[note()])])],
        signatures=signatures,
    )
    path = tmp_path / "ts.gp5"

    GP5Writer().write(ir, str(path))

    song = gp.parse(str(path), encoding="cp936")
    headers = song.measureHeaders
    assert headers[1].timeSignature.numerator == 2
