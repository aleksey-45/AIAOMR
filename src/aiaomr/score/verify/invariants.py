"""事后检查：只看读出来的结果，找前后矛盾（规格 §2.5 F-01..F-04、§6.1 A1..A5）。

检查不通过只产生报警，不中断（F-04）；也不补写任何 beat（F-02）。
本模块是纯函数：不碰文件、不发请求。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...kernel.contracts import MeasureRead, Skeleton
from ...kernel.ir import Beat, Note, TimeSignature

# 时值换算：1/32 拍为 1 tick（quarter = 8）。
_TICKS = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2, "32nd": 1}
_DOT_FACTORS = {0: 1.0, 1: 1.5, 2: 1.75}


@dataclass
class Alarm:
    """一条报警：规则号、小节、声称值、期望值、证据（F-03）。"""

    rule: str
    measure: int
    claimed: object
    expected: object
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "measure": self.measure,
            "claimed": self.claimed,
            "expected": self.expected,
            "evidence": self.evidence,
        }


def ticks_of(beat: Beat) -> int:
    return int(round(_TICKS[beat.duration] * _DOT_FACTORS[beat.dots]))


def effective_ts(time_signatures: list[TimeSignature], measure: int) -> TimeSignature | None:
    """取该小节生效的拍号：事件列表里 measure ≤ 当前小节的最后一条（§3.1 不变量）。"""
    current = None
    for signature in time_signatures:
        if signature.measure <= measure:
            current = signature
        else:
            break
    return current


def expected_ticks(signature: TimeSignature) -> int:
    return int(round(signature.beats * 32 / signature.beatType))


def _evidence(beat: Beat) -> dict:
    return {
        "system": beat.evidence.system,
        "crop": list(beat.evidence.crop),
        "call": beat.evidence.call,
    }


def _iter_notes(reads: list[MeasureRead]):
    for read in reads:
        for beat in read.beats:
            for note in beat.notes:
                yield read.index, beat, note


def check_bar_duration(reads: list[MeasureRead], skeleton: Skeleton) -> list[Alarm]:
    """A1：非 rest 小节的时值之和 == 该小节生效的拍号。"""
    alarms: list[Alarm] = []
    for read in reads:
        if read.unreadable or not read.beats:
            continue
        if all(beat.rest for beat in read.beats):
            continue
        signature = effective_ts(skeleton.timeSignatures, read.index)
        if signature is None:
            continue
        actual = sum(ticks_of(beat) for beat in read.beats)
        expected = expected_ticks(signature)
        if actual != expected:
            alarms.append(
                Alarm(
                    rule="A1",
                    measure=read.index,
                    claimed=actual,
                    expected=expected,
                    evidence=_evidence(read.beats[0]),
                )
            )
    return alarms


def check_pitch_identity(reads: list[MeasureRead], skeleton: Skeleton) -> list[Alarm]:
    """A2：模型从五线谱读到的 MIDI == tuning[string-1] + fret；缺失 pitchClaim 时跳过。"""
    alarms: list[Alarm] = []
    for index, _beat, note in _iter_notes(reads):
        if note.pitchClaim is None:
            continue
        expected = skeleton.tuning[note.string - 1] + note.fret
        if note.pitchClaim != expected:
            alarms.append(
                Alarm(
                    rule="A2",
                    measure=index,
                    claimed=note.pitchClaim,
                    expected=expected,
                    evidence={"string": note.string, "fret": note.fret, "call": _beat.evidence.call},
                )
            )
    return alarms


def check_range(reads: list[MeasureRead], skeleton: Skeleton) -> list[Alarm]:
    """A3：string ∈ 1..N、fret ∈ 0..fretCount。"""
    alarms: list[Alarm] = []
    for index, _beat, note in _iter_notes(reads):
        if not 1 <= note.string <= skeleton.stringCount:
            alarms.append(
                Alarm(rule="A3", measure=index, claimed=note.string,
                      expected=[1, skeleton.stringCount], evidence={"kind": "string"})
            )
        if not 0 <= note.fret <= skeleton.fretCount:
            alarms.append(
                Alarm(rule="A3", measure=index, claimed=note.fret,
                      expected=[0, skeleton.fretCount], evidence={"kind": "fret"})
            )
    return alarms


def check_digit_head(reads: list[MeasureRead]) -> list[Alarm]:
    """A4/A4b：数字数 ≤ 音头数；比的是"数字"不是"字形"。

    `12` 是一个数字、两个字形：把字形数（13）拿去和音头数（7）比会误报，所以这里只数
    带 digit 的音符个数。一个音符没有数字、又没标成连音后半，报 A4b。
    """
    alarms: list[Alarm] = []
    for index, beat, note in _iter_notes(reads):
        if note.digit is None and not note.tieFromPrevious:
            alarms.append(
                Alarm(rule="A4b", measure=index, claimed="notehead", expected="digit or tieFromPrevious",
                      evidence=_evidence(beat))
            )
    for read in reads:
        notes: list[Note] = [note for beat in read.beats for note in beat.notes]
        digits = sum(1 for note in notes if note.digit is not None)
        heads = len(notes)
        if digits > heads:
            alarms.append(
                Alarm(rule="A4", measure=read.index, claimed=digits, expected=f"<= {heads}",
                      evidence={})
            )
    return alarms


def check_tuning_implied(reads: list[MeasureRead], skeleton: Skeleton) -> list[Alarm]:
    """A5：由 pitchClaim − fret 反解出来的调弦，与声明的调弦一致。"""
    deltas: dict[int, int] = {}
    for _index, _beat, note in _iter_notes(reads):
        if note.pitchClaim is None or not 1 <= note.string <= len(skeleton.tuning):
            continue
        delta = note.pitchClaim - note.fret - skeleton.tuning[note.string - 1]
        deltas[delta] = deltas.get(delta, 0) + 1
    if not deltas:
        return []
    mode, count = max(deltas.items(), key=lambda item: item[1])
    if mode == 0 or count < 3:
        return []
    return [Alarm(rule="A5", measure=0, claimed=mode, expected=0,
                  evidence={"count": count, "deltas": deltas})]


def check_all(reads: list[MeasureRead], skeleton: Skeleton) -> list[Alarm]:
    """跑完本计划实现的五条规则，返回报警列表（不抛异常、不阻断）。"""
    alarms: list[Alarm] = []
    alarms.extend(check_bar_duration(reads, skeleton))
    alarms.extend(check_pitch_identity(reads, skeleton))
    alarms.extend(check_range(reads, skeleton))
    alarms.extend(check_digit_head(reads))
    alarms.extend(check_tuning_implied(reads, skeleton))
    return alarms
