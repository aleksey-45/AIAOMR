"""GP5 写出（规格 §4.3、E-01..E-05）。

三步：`validate`（能写吗）→ `build`（写）→ `verify`（写出来再读回来逐音核对）。
弦号翻转**只在这里**发生一次：IR 1 = 最低音弦，GP 1 = 最高音弦（E-02）。
文本按 cp936 编码；编不进去就报错，绝不写乱码（E-03/E-04）。
"""

from __future__ import annotations

import os
from pathlib import Path

import guitarpro as gp

from ...kernel.errors import ErrorCode
from ...kernel.ir import IR, Measure, TimeSignature
from ..base import Report, WriterError

NAME = "gp5"
ENCODING = "cp936"

# IR 时值 → PyGuitarPro 的 Duration 值（1 = whole，4 = quarter，依此类推）。
_DURATIONS = {
    "whole": gp.Duration.whole,
    "half": gp.Duration.half,
    "quarter": gp.Duration.quarter,
    "eighth": gp.Duration.eighth,
    "16th": gp.Duration.sixteenth,
    "32nd": gp.Duration.thirtySecond,
}


def _ticks(duration: str, dots: int) -> int:
    base = int(gp.Duration.quarterTime * 4 // _DURATIONS[duration])
    return int(round(base * (1.5 if dots == 1 else 1.75 if dots == 2 else 1.0)))


def _bar_ticks(signature: TimeSignature) -> int:
    return int(round(signature.beats * (4 * gp.Duration.quarterTime) / signature.beatType))


def _effective(events: list, measure: int):
    current = None
    for event in events:
        if event.measure <= measure:
            current = event
        else:
            break
    return current


_DEFAULT_SIGNATURE = TimeSignature(measure=1, beats=4, beatType=4)


def _effective_or_default(events: list, measure: int) -> TimeSignature:
    """没有生效拍号时按 4/4 写（并记 warning）：拍号缺失是报警，不是写出阻断。"""
    return _effective(events, measure) or _DEFAULT_SIGNATURE


def _rest_duration(bar_ticks: int):
    for value in (gp.Duration.whole, gp.Duration.half, gp.Duration.quarter,
                  gp.Duration.eighth, gp.Duration.sixteenth):
        if int(gp.Duration.quarterTime * 4 // value) == bar_ticks:
            return gp.Duration(value)
    # 3/4 这种整小节没有单一基本时值，用附点二分（time = bar）
    if int(round(gp.Duration(gp.Duration.half).time * 1.5)) == bar_ticks:
        return gp.Duration(gp.Duration.half, isDotted=True)
    return gp.Duration(gp.Duration.whole)


class GP5Writer:
    name = NAME

    # ---- 第一步：校验 --------------------------------------------------
    def validate(self, ir: IR) -> list[str]:
        """返回错误列表；空列表表示可以写。

        这里只判断"结构上能不能表达"，不做音乐正确性判断：小节时值合计对不上拍号
        属于 A1 报警（§6.1），报警不阻断（F-04），不在这里拒绝。
        """
        errors: list[str] = []
        if not ir.measures:
            errors.append("measures 为空")
        if ir.score.stringCount != len(ir.score.tuning):
            errors.append("tuning 长度与 stringCount 不一致")
        for field in ("title", "artist", "tabber"):
            value = getattr(ir.score, field) or ""
            try:
                value.encode(ENCODING)
            except UnicodeEncodeError:
                errors.append(f"{field} 无法用 {ENCODING} 编码：{value!r}")

        for measure in ir.measures:
            if measure.rest:
                continue
            if not measure.beats:
                errors.append(f"小节 {measure.index}: 没有 beat 也不是休止小节")
                continue
            for beat_index, beat in enumerate(measure.beats, start=1):
                if beat.duration not in _DURATIONS:
                    errors.append(f"小节 {measure.index} 拍 {beat_index}: 不认识的时值 {beat.duration!r}")
                    continue
                if beat.dots >= 2:
                    errors.append(f"小节 {measure.index} 拍 {beat_index}: dots=2 暂不支持（§4.3）")
                    continue
                if not beat.notes and not beat.rest:
                    errors.append(f"小节 {measure.index} 拍 {beat_index}: 既没有音符也没有标休止")
                for note in beat.notes:
                    if not 1 <= note.string <= ir.score.stringCount:
                        errors.append(f"小节 {measure.index}: 弦号 {note.string} 越界")
                    if not 0 <= note.fret <= ir.score.fretCount:
                        errors.append(f"小节 {measure.index}: 品数 {note.fret} 越界")

        for event in ir.score.keySignatures:
            if not hasattr(gp.KeySignature, event.key):
                errors.append(f"不认识的调号：{event.key!r}")
        return errors

    def warnings(self, ir: IR) -> list[str]:
        """不阻断、但要在报告里记一笔的事。"""
        warnings: list[str] = []
        if any(_effective(ir.score.timeSignatures, m.index) is None for m in ir.measures):
            warnings.append("有生效拍号缺失，已按 4/4 写出")
        return warnings

    # ---- 第二步：构建并写出 --------------------------------------------
    def build(self, ir: IR) -> gp.Song:
        song = gp.Song()
        song.tracks.clear()
        song.measureHeaders.clear()

        song.title = ir.score.title or ""
        song.artist = ir.score.artist or ""
        song.tabber = ir.score.tabber or ""
        song.tempo = ir.score.tempos[0].bpm if ir.score.tempos else 120

        tuning = list(ir.score.tuning)
        n_strings = len(tuning)
        track = gp.Track(song, number=1, name="Bass")
        # IR 低音弦在前；GP 弦号 1 = 最高音弦，列表位置对应弦号，所以这里反转一次（E-02）。
        track.strings = [
            gp.GuitarString(number=index + 1, value=tuning[n_strings - 1 - index])
            for index in range(n_strings)
        ]
        track.channel.instrument = 33  # fingered bass
        track.fretCount = int(ir.score.fretCount)
        track.clefTranspose = int(ir.score.clefTranspose)
        track.settings.notation = True
        track.settings.tablature = True
        track.settings.diagramsAreBelow = False
        song.tracks.append(track)

        for _measure in ir.measures:
            song.newMeasure()
        for measure in ir.measures:
            header = song.measureHeaders[measure.index - 1]
            signature = _effective_or_default(ir.score.timeSignatures, measure.index)
            header.timeSignature = gp.TimeSignature(
                signature.beats, gp.Duration(signature.beatType)
            )
            key = _effective(ir.score.keySignatures, measure.index)
            if key is not None:
                header.keySignature = getattr(gp.KeySignature, key.key)

        for measure in ir.measures:
            self._write_measure(track, measure, ir)

        text = f"{ir.score.title}{ir.score.artist}{ir.score.tabber}"
        text.encode(ENCODING)  # 再确认一次：只要有一个字符编不进去就不写
        return song

    def _write_measure(self, track, measure: Measure, ir: IR) -> None:
        voice = track.measures[measure.index - 1].voices[0]
        signature = _effective_or_default(ir.score.timeSignatures, measure.index)
        bar_ticks = _bar_ticks(signature)
        if measure.rest:
            voice.beats.append(
                gp.Beat(voice, duration=_rest_duration(bar_ticks), status=gp.BeatStatus.rest)
            )
            return
        n_strings = ir.score.stringCount
        for beat in measure.beats:
            gp_beat = gp.Beat(
                voice,
                duration=gp.Duration(_DURATIONS[beat.duration], isDotted=beat.dots == 1),
                status=gp.BeatStatus.rest if beat.rest else gp.BeatStatus.normal,
            )
            for note in beat.notes:
                gp_note = gp.Note(
                    gp_beat,
                    value=note.fret,
                    string=n_strings - note.string + 1,  # 唯一翻转点（E-02）
                )
                # GP5 里只有"接上一条延音"的这条记 tie；延音起点是普通音符。
                # 起点也记 tie 的话，PyGuitarPro 重读时会按"延音链"把它的品数
                # 解析成上一音的值（getTiedNoteValue），往返核对就会错。
                if note.tieFromPrevious:
                    gp_note.type = gp.NoteType.tie
                gp_beat.notes.append(gp_note)
            voice.beats.append(gp_beat)

    # ---- 第三步：写盘 + 往返核对 ---------------------------------------
    def write(self, ir: IR, path: str) -> Report:
        errors = self.validate(ir)
        if errors:
            raise WriterError(ErrorCode.E_BUILD_VALIDATE, "写出前校验失败", errors)
        warnings = self.warnings(ir)

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        try:
            song = self.build(ir)
            gp.write(song, str(temporary), encoding=ENCODING)
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

        problems = self.verify(ir, target)
        if problems:
            raise WriterError(ErrorCode.E_BUILD_ROUNDTRIP, "写出的文件与 IR 不一致", problems)
        return Report(
            path=str(target),
            bytes=target.stat().st_size,
            measures=len(ir.measures),
            roundtrip="OK",
            warnings=warnings,
        )

    def verify(self, ir: IR, path: Path) -> list[str]:
        """重新解析写出的文件，逐小节、逐拍、逐音对比 IR。"""
        song = gp.parse(str(path), encoding=ENCODING)
        problems: list[str] = []
        if song.title != (ir.score.title or ""):
            problems.append(f"title {song.title!r} != {ir.score.title!r}")
        if song.artist != (ir.score.artist or ""):
            problems.append(f"artist {song.artist!r} != {ir.score.artist!r}")
        if len(song.tracks) != 1:
            problems.append(f"期望 1 条轨，实际 {len(song.tracks)}")

        n_strings = ir.score.stringCount
        want_strings = [(i + 1, ir.score.tuning[n_strings - 1 - i]) for i in range(n_strings)]
        got_strings = [(s.number, s.value) for s in song.tracks[0].strings]
        if got_strings != want_strings:
            problems.append(f"tuning {got_strings} != {want_strings}")

        track = song.tracks[0]
        if len(track.measures) != len(ir.measures):
            problems.append(f"小节数 {len(track.measures)} != {len(ir.measures)}")
        for measure in ir.measures:
            index = measure.index - 1
            beats = track.measures[index].voices[0].beats
            if measure.rest:
                if len(beats) != 1 or beats[0].status != gp.BeatStatus.rest:
                    problems.append(f"小节 {measure.index}: 期望一个休止拍，实际 {len(beats)} 拍")
                continue
            if len(beats) != len(measure.beats):
                problems.append(f"小节 {measure.index}: {len(beats)} 拍 != {len(measure.beats)} 拍")
                continue
            for beat_index, (got, want) in enumerate(zip(beats, measure.beats), start=1):
                if (got.duration.value, got.duration.isDotted) != (_DURATIONS[want.duration],
                                                                   want.dots == 1):
                    problems.append(f"小节 {measure.index} 拍 {beat_index}: 时值不一致")
                if bool(got.status == gp.BeatStatus.rest) != want.rest:
                    problems.append(f"小节 {measure.index} 拍 {beat_index}: 休止标记不一致")
                got_notes = sorted((n.string, n.value) for n in got.notes)
                want_notes = sorted((n_strings - n.string + 1, n.fret) for n in want.notes)
                if got_notes != want_notes:
                    problems.append(f"小节 {measure.index} 拍 {beat_index}: 音符 {got_notes} != {want_notes}")
                got_ties = sorted(i for i, n in enumerate(got.notes) if n.type == gp.NoteType.tie)
                want_ties = sorted(i for i, n in enumerate(want.notes)
                                   if n.tieFromPrevious)
                if got_ties != want_ties:
                    problems.append(f"小节 {measure.index} 拍 {beat_index}: 连音 {got_ties} != {want_ties}")
        return problems
