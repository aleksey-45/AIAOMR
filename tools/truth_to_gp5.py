#!/usr/bin/env python
"""把真值 JSON 写成一份 `.gp5` 副本（`docs/spec-v3.md` §9.3 的语料约定）。

为什么要有这个工具：`NIGHT DANCER`、`Клетка` 的真值是 `.gpx`（`score.gpif` 打包成 zip，
只是后缀叫 `.gp`），PyGuitarPro 读不了，人工比对和评测都得先转换，很麻烦。这里把
`tools/dump.mjs` 导出的真值 JSON 走一遍本项目的 IR，再用 `writers/gp5/` 写成 `.gp5`，
副本和产物用同一套写出代码，不需要另装转换器。

保留的东西：拍号、调号、速度、调弦、弦数、逐拍时值与附点、弦号/品位/音高、连音（tie）。
丢掉的东西（真值导出里没有，或 GP5 表达不了）：技巧（滑音、击勾、闷音……）、反复与跳房子、
力度、歌词、多声部。副本是"音符与时间的正确答案"，不是原谱的完整复刻。

用法：
    .venv/Scripts/python.exe tools/truth_to_gp5.py --truth out/p1/NIGHT\\ DANCER/truth.json \\
        --out corpus/truth/NIGHT\\ DANCER.gp5 --song "NIGHT DANCER"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aiaomr.kernel.ir import (  # noqa: E402
    Beat,
    Evidence,
    IR,
    KeySignature,
    Measure,
    Meta,
    Note,
    Score,
    SkeletonProvenance,
    Source,
    Tempo,
    TimeSignature,
)
from aiaomr.writers.gp5.writer import GP5Writer  # noqa: E402

# alphaTab 的 Duration 枚举 → 本项目的时值名。
DURATION_BY_ENUM = {1: "whole", 2: "half", 4: "quarter", 8: "eighth", 16: "16th", 32: "32nd"}
# alphaTab 的 MIDI tick（四分 = 960）→ 时值名，退化路径用。
DURATION_BY_TICKS = {
    3840: "whole",
    2880: "half",
    1920: "half",
    1440: "quarter",
    960: "quarter",
    720: "eighth",
    480: "eighth",
    360: "16th",
    240: "16th",
    120: "32nd",
}
# GP5 的调号数值 → PyGuitarPro 的枚举名（升号为正、降号为负）。
KEY_BY_NUMBER = {
    0: "CMajor",
    1: "GMajor",
    2: "DMajor",
    3: "AMajor",
    4: "EMajor",
    5: "BMajor",
    6: "FMajorSharp",
    7: "CMajorSharp",
    -1: "FMajor",
    -2: "BMajorFlat",
    -3: "EMajorFlat",
    -4: "AMajorFlat",
    -5: "DMajorFlat",
    -6: "GMajorFlat",
    -7: "CMajorFlat",
}
ENCODING = "cp936"


def _events(measures, pick):
    """把逐小节相同的值压成 `{measure, value}` 事件列表（值变化处才是事件）。"""
    out = []
    previous = None
    for measure in measures:
        value = pick(measure)
        if value is None or value == previous:
            continue
        out.append({"measure": measure["index"], "value": value})
        previous = value
    return out


def build_ir(truth: dict, song: str) -> tuple[IR, list[str]]:
    """真值 JSON → IR。返回 IR 和一批"副本里丢掉了什么/改了什么"的说明。"""
    notes_about: list[str] = []
    tuning = list(truth["tuning"])
    string_count = len(tuning)
    ticks_per_project = 120  # alphaTab 四分=960，本项目四分=8；换算只为对账，见下。

    base_count = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2, "32nd": 1}
    measures: list[Measure] = []
    for item in truth["measures"]:
        beats: list[Beat] = []
        for position, raw in enumerate(item["beats"], start=1):
            duration = DURATION_BY_ENUM.get(raw.get("duration"))
            if duration is None:
                duration = DURATION_BY_TICKS.get(raw["ticks"])
            if duration is None:
                raise ValueError(f"小节 {item['index']} 拍 {position}: 时值 {raw} 无法映射")
            base = base_count[duration] * ticks_per_project
            dots = int(raw.get("dots", 0))
            factor = {0: 1.0, 1: 1.5, 2: 1.75}.get(dots, 1.0)
            if abs(raw["ticks"] - round(base * factor)) > 1:
                raise ValueError(
                    f"小节 {item['index']} 拍 {position}: tick {raw['ticks']} 与 "
                    f"{duration}（附点 {dots}）对不上"
                )
            notes = []
            for note in raw["notes"]:
                pitch = tuning[note["string"] - 1] + note["fret"]
                if pitch != note["pitch"]:
                    notes_about.append(
                        f"小节 {item['index']}: 弦 {note['string']} 品 {note['fret']} 的"
                        f"音高按调弦算是 {pitch}，真值给 {note['pitch']}，副本用算出来的值"
                    )
                notes.append(
                    Note(
                        string=int(note["string"]),
                        fret=int(note["fret"]),
                        pitch=pitch,
                        tie=bool(note.get("tie", False)),
                        tieFromPrevious=bool(note.get("tieFromPrevious", False)),
                    )
                )
            beats.append(
                Beat(
                    duration=duration,
                    dots=min(dots, 1) if dots else 0,
                    rest=bool(raw["rest"]),
                    notes=notes,
                    prov="derived",
                    evidence=Evidence(system=1, crop=[0, 0, 0, 0], call="truth"),
                )
            )
        measures.append(Measure(index=item["index"], printed=None, beats=beats))

    time_signatures = [
        TimeSignature(measure=event["measure"], beats=event["value"]["numerator"],
                      beatType=event["value"]["denominator"])
        for event in _events(truth["measures"], lambda m: m.get("timeSignature"))
    ]
    key_events = _events(truth["measures"], lambda m: m.get("keySignature"))
    key_signatures: list[KeySignature] = []
    for event in key_events:
        name = KEY_BY_NUMBER.get(event["value"])
        if name is None:
            notes_about.append(f"小节 {event['measure']}: 调号 {event['value']} 不认识，副本按 C 写")
            name = "CMajor"
        key_signatures.append(KeySignature(measure=event["measure"], key=name))

    title = (truth.get("title") or song or "").strip()
    try:
        title.encode(ENCODING)
    except UnicodeEncodeError:
        notes_about.append(f"曲名 {title!r} 无法用 {ENCODING} 写出，副本标题置空（文件名保留曲名）")
        title = ""

    ir = IR(
        meta=Meta(
            provider="truth",
            model="dump.mjs",
            promptVersion="truth",
            generatedAt=datetime.now(timezone.utc),
        ),
        source=Source(**{"class": 3}, kind="truth",
                        files=[str(truth.get("sourcePath", ""))], inputSha256="truth"),
        score=Score(
            title=title,
            artist="",
            tuning=tuning,
            stringCount=string_count,
            timeSignatures=time_signatures,
            keySignatures=key_signatures,
            tempos=[Tempo(measure=1, bpm=int(truth.get("tempo") or 120))],
            clefTranspose=-12,
            fretCount=24,
        ),
        skeletonProvenance=SkeletonProvenance(
            timeSignatures="read",
            tuning="read",
            keySignatures="read",
            tempos="read",
            title="read",
            artist="empty",
        ),
        measures=measures,
    )
    return ir, notes_about


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="真值 JSON → .gp5 副本")
    parser.add_argument("--truth", required=True, help="tools/dump.mjs 导出的真值 JSON")
    parser.add_argument("--out", required=True, help="输出的 .gp5 路径")
    parser.add_argument("--song", default=None, help="曲名（默认取真值标题或文件名）")
    args = parser.parse_args(argv)

    truth_path = Path(args.truth)
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    if not truth.get("available", True):
        raise SystemExit(f"真值不可用：{truth.get('error', truth_path)}")
    truth.setdefault("sourcePath", str(truth_path))

    song = args.song or truth_path.parent.name or truth_path.stem
    ir, about = build_ir(truth, song)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = GP5Writer().write(ir, str(out_path))

    notes = sum(len(beat.notes) for measure in ir.measures for beat in measure.beats)
    print(json.dumps({
        "out": str(out_path),
        "bytes": report.bytes,
        "roundtrip": report.roundtrip,
        "measures": len(ir.measures),
        "beats": sum(len(measure.beats) for measure in ir.measures),
        "notes": notes,
        "notes_about": about[:12],
        "notes_about_total": len(about),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
