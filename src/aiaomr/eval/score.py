"""打分器（规格 §2.9 EV-01..EV-04、§9.2）。

四个指标，每个都带分母；先自测尺子，再量分数。真值来自旧项目存好的 `.gp`，用
`tools/dump.mjs` 导成 JSON（alphaTab 的弦号从最低弦数起，与本项目约定一致）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..kernel.contracts import Skeleton
from ..kernel.ir import IR
from ..score.verify.invariants import effective_ts, expected_ticks, ticks_of

DEFAULT_THRESHOLDS = {
    "alignment": 0.98,
    "string_fret": 0.90,
    "pitch_exact": 0.85,
    "bars_add_up": 0.95,
}


class EvalError(RuntimeError):
    """尺子不可信（自测没通过），拒绝打分。"""


@dataclass(frozen=True)
class Metric:
    value: float
    matched: int
    total: int

    def as_dict(self) -> dict:
        return {"value": round(self.value, 4), "matched": self.matched, "total": self.total}


def load_truth(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not data.get("available", True):
        raise EvalError(f"真值不可用：{data.get('error', path)}")
    return data


def _ir_pairs(ir: IR) -> dict[int, list[tuple[int, int, int]]]:
    out: dict[int, list[tuple[int, int, int]]] = {}
    for measure in ir.measures:
        out[measure.index] = [
            (note.string, note.fret, note.pitch)
            for beat in measure.beats
            for note in beat.notes
        ]
    return out


def _truth_pairs(truth: dict) -> dict[int, list[tuple[int, int, int]]]:
    out: dict[int, list[tuple[int, int, int]]] = {}
    for measure in truth.get("measures", []):
        pairs = []
        for beat in measure.get("beats", []):
            for note in beat.get("notes", []):
                pairs.append((int(note["string"]), int(note["fret"]), int(note["pitch"])))
        out[int(measure["index"])] = pairs
    return out


def _multiset_match(left: list, right: list) -> int:
    remaining = list(right)
    matched = 0
    for item in left:
        if item in remaining:
            remaining.remove(item)
            matched += 1
    return matched


def measure(ir: IR, truth: dict, max_measures: int | None = None) -> dict[str, Metric]:
    """IR 对真值打分，返回四个指标。"""
    truth_pairs = _truth_pairs(truth)
    ir_pairs = _ir_pairs(ir)
    indices = sorted(truth_pairs)
    if max_measures is not None:
        indices = indices[:max_measures]

    aligned = sum(1 for index in indices if index in ir_pairs)
    total_truth = sum(len(truth_pairs[index]) for index in indices)
    string_matched = 0
    pitch_matched = 0
    for index in indices:
        truth_flat = [(s, f) for s, f, _p in truth_pairs[index]]
        ir_flat = [(s, f) for s, f, _p in ir_pairs.get(index, [])]
        string_matched += _multiset_match(ir_flat, truth_flat)
        pitch_matched += _multiset_match(
            [(s, f, p) for s, f, p in ir_pairs.get(index, [])],
            truth_pairs[index],
        )

    ok_bars = 0
    for measure_obj in ir.measures:
        signature = effective_ts(ir.score.timeSignatures, measure_obj.index)
        if signature is None:
            continue
        if measure_obj.rest:
            ok_bars += 1
            continue
        if sum(ticks_of(beat) for beat in measure_obj.beats) == expected_ticks(signature):
            ok_bars += 1
    bars_total = len(ir.measures)

    return {
        "alignment": Metric(aligned / len(indices) if indices else 0.0, aligned, len(indices)),
        "string_fret": Metric(string_matched / total_truth if total_truth else 0.0,
                              string_matched, total_truth),
        "pitch_exact": Metric(pitch_matched / total_truth if total_truth else 0.0,
                              pitch_matched, total_truth),
        "bars_add_up": Metric(ok_bars / bars_total if bars_total else 0.0, ok_bars, bars_total),
    }


def _perfect() -> tuple[IR, dict]:
    """一个完美答案：4/4、四拍、每拍一个音。"""
    from datetime import datetime, timezone

    from ..kernel.ir import Beat, Evidence, Measure, Meta, Note, Score, SkeletonProvenance, Source, Structure, TimeSignature

    evidence = Evidence(system=1, crop=[0, 0, 1, 1], call="selftest")
    beats = []
    truth_beats = []
    for fret in (0, 2, 3, 5):
        note = Note(string=2, fret=fret, tie=False, tieFromPrevious=False, techniques=[],
                    pitch=33 + fret, pitchClaim=33 + fret)
        beats.append(Beat(duration="quarter", dots=0, rest=False, notes=[note],
                          prov="read", evidence=evidence))
        truth_beats.append({"ticks": 960, "rest": False,
                            "notes": [{"string": 2, "fret": fret, "pitch": 33 + fret}]})
    ir = IR(
        meta=Meta(provider="selftest", model="selftest", promptVersion="p0",
                  schemaVersion="3.0", generatedAt=datetime.now(timezone.utc)),
        source=Source(**{"class": 3}, kind="image", files=[], inputSha256=""),
        score=Score(title="", artist="", tabber="", tuning=[28, 33, 38, 43], stringCount=4,
                    timeSignatures=[TimeSignature(measure=1, beats=4, beatType=4)],
                    keySignatures=[], tempos=[], clefTranspose=-12, fretCount=24),
        skeletonProvenance=SkeletonProvenance(
            timeSignatures="read", tuning="read", keySignatures="defaulted",
            tempos="defaulted", title="filename", artist="empty"),
        measures=[Measure(index=1, printed=None, rest=False, multiRest=1, beats=beats)],
        structure=Structure(), judgements=[], build=None,
    )
    truth = {"available": True, "tuning": [28, 33, 38, 43],
             "measures": [{"index": 1, "beats": truth_beats}]}
    return ir, truth


def selftest() -> None:
    """尺子自测：完美答案是满分；已知破坏必须让对应指标下降，测不出来就拒绝打分。"""
    ir, truth = _perfect()
    perfect = measure(ir, truth)
    if any(metric.value != 1.0 for metric in perfect.values()):
        raise EvalError(f"完美答案不是满分：{ {k: v.value for k, v in perfect.items()} }")

    worse = _perfect()[0]
    worse.measures[0].beats[0].notes[0].fret = 1
    worse.measures[0].beats[0].notes[0].pitch = 34
    degraded = measure(worse, truth)
    for name in ("string_fret", "pitch_exact"):
        if degraded[name].value >= perfect[name].value:
            raise EvalError(f"破坏之后 {name} 没有下降，尺子不可信")

    short = _perfect()[0]
    short.measures[0].beats[1].duration = "eighth"
    if measure(short, truth)["bars_add_up"].value >= perfect["bars_add_up"].value:
        raise EvalError("改掉时值之后 bars_add_up 没有下降，尺子不可信")
