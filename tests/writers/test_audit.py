"""alphaTab 审计的测试（规格 §4.4；计划任务 12）。没装 Node 或 alphaTab 时跳过。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import guitarpro as gp
import pytest

from aiaomr.writers.audit import audit, audit_passed
from aiaomr.writers.gp5.writer import GP5Writer
from tests.writers.test_gp5 import beat, four_quarters, make_ir, measure, note

ALPHATAB = os.environ.get("ALPHATAB_PATH", "")
HAVE_NODE = shutil.which("node") is not None
HAVE_ALPHATAB = bool(ALPHATAB) and Path(ALPHATAB).exists()

pytestmark = pytest.mark.skipif(
    not (HAVE_NODE and HAVE_ALPHATAB),
    reason="需要 node 与 ALPHATAB_PATH 指向 alphaTab.core.mjs",
)


def test_legal_gp5_has_zero_errors(tmp_path: Path) -> None:
    path = tmp_path / "ok.gp5"
    GP5Writer().write(make_ir([measure(1, beats=four_quarters())]), str(path))

    result = audit(path)

    assert result["available"] is True
    assert audit_passed(result) is True
    assert result["notes"] >= 4


def test_wrong_bar_duration_is_caught(tmp_path: Path) -> None:
    song = gp.Song()
    song.tracks.clear()
    song.measureHeaders.clear()
    track = gp.Track(song, number=1, name="Bass")
    track.strings = [gp.GuitarString(number=i + 1, value=v) for i, v in enumerate([43, 38, 33, 28])]
    song.tracks.append(track)
    song.newMeasure()
    voice = track.measures[0].voices[0]
    for _ in range(3):  # 4/4 里只放三拍
        gp_beat = gp.Beat(voice, duration=gp.Duration(gp.Duration.quarter),
                          status=gp.BeatStatus.normal)
        gp_note = gp.Note(gp_beat, value=3, string=1)
        gp_beat.notes.append(gp_note)
        voice.beats.append(gp_beat)
    path = tmp_path / "bad_bar.gp5"
    gp.write(song, str(path), encoding="cp936")

    result = audit(path)

    assert result["available"] is True
    assert result["barErrors"] >= 1
