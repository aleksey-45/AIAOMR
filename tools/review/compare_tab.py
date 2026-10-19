#!/usr/bin/env python
"""人工审核用：把模型读到的 TAB（弦号 + 品数）与真值逐小节比对。

用法：
    .venv/Scripts/python.exe tools/review/compare_tab.py \
        --measures out/nd-check/measures --truth out/p1/NIGHT DANCER/truth.json

真值来自 `tools/dump.mjs` 导出的 JSON（弦号约定与 IR 一致：1 = 最低音弦）。
模型读数来自 `out/<song>/measures/*.json`（`MeasureResult`）。

输出：一段人读摘要 + 一个 JSON。判定"这一小节 TAB 正确"= 每一拍的 (弦号, 品数)
多重集与真值完全一致；多小节休止条按 `multiRest` 展开后只要求对应的真值小节是空小节。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def _truth_measures(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["measures"]


def _reads(measures_dir: Path) -> list[dict]:
    out: list[dict] = []
    for path in sorted(measures_dir.glob("*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        for read in result.get("reads", []):
            out.append(read)
    out.sort(key=lambda read: read["index"])
    return out


def _tab(beat: dict) -> Counter:
    return Counter((note["string"], note["fret"]) for note in beat.get("notes", []))


def _beat_key(beat: dict) -> tuple:
    return (bool(beat.get("rest")), beat.get("duration"), beat.get("dots", 0), tuple(sorted(_tab(beat).items())))


def _all_rest(measure: dict) -> bool:
    """真值小节：所有 beat 都是休止（含空声部被折叠成空的情形）。"""
    return all(beat.get("rest") for beat in measure.get("beats", [])) or not measure.get("beats")


def _read_all_rest(read: dict) -> bool:
    beats = read.get("beats") or []
    return bool(beats) and all(beat.get("rest") for beat in beats)


def _read_tab(read: dict) -> Counter:
    out: Counter = Counter()
    for beat in read.get("beats", []):
        out.update(_tab(beat))
    return out


def _truth_tab(measure: dict) -> Counter:
    out: Counter = Counter()
    for beat in measure.get("beats", []):
        out.update(_tab(beat))
    return out


def align(reads: list[dict], truth: list[dict]) -> list[tuple[int, int]]:
    """模型读数与真值小节的单调序列对齐（Needleman–Wunsch）。

    不能"一小节对一小节"：多小节休止在谱面上只是一个显示小节，真值里是 N 个小节，
    模型也不一定报 `multiRest`（NIGHT DANCER 实测全报 1）。所以按 TAB 内容打分对齐：
    弦号+品数多重集相同 = 匹配；否则低分；插空惩罚。返回 [(read 下标, truth 下标)]。
    """
    equal_score, mismatch_score = 1.0, -0.6
    read_gap_score = -0.9          # 允许跳过读数（读不出来/多余显示小节）
    rest_gap_score = -0.3          # 只允许跳过"真值是休止"的小节（多小节休止展开）
    n, m = len(reads), len(truth)
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    move = [[""] * (m + 1) for _ in range(n + 1)]
    truth_tabs = [_truth_tab(measure) for measure in truth]
    for i in range(1, n + 1):
        score[i][0] = score[i - 1][0] + read_gap_score
        move[i][0] = "up"
    for j in range(1, m + 1):
        # 开头只允许跳过休止小节；非休止小节必须被某个读数覆盖
        allowed = rest_gap_score if not truth_tabs[j - 1] else -1e9
        score[0][j] = score[0][j - 1] + allowed
        move[0][j] = "left"
    for i in range(1, n + 1):
        read_tab = _read_tab(reads[i - 1])
        for j in range(1, m + 1):
            diagonal = score[i - 1][j - 1] + (equal_score if read_tab == truth_tabs[j - 1] else mismatch_score)
            up = score[i - 1][j] + read_gap_score
            left = score[i][j - 1] + (rest_gap_score if not truth_tabs[j - 1] else -1e9)
            best, direction = diagonal, "diag"
            if up > best:
                best, direction = up, "up"
            if left > best:
                best, direction = left, "left"
            score[i][j] = best
            move[i][j] = direction
    pairs: list[tuple[int, int]] = []
    i, j = n, m
    while i > 0 or j > 0:
        direction = move[i][j]
        if direction == "diag":
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif direction == "up":
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def compare(reads: list[dict], truth: list[dict]) -> dict:
    pairs = align(reads, truth)
    matched_reads = {index for index, _ in pairs}
    matched_truth = {index for _, index in pairs}
    report = {
        "displayedBars": len(reads),
        "truthMeasures": len(truth),
        "alignedPairs": len(pairs),
        "tabExact": 0,
        "fretExact": 0,
        "tabCompared": 0,
        "restPairs": 0,
        "unmatchedReads": [reads[index]["index"] for index in range(len(reads)) if index not in matched_reads],
        "unmatchedTruth": [truth[index]["index"] for index in range(len(truth)) if index not in matched_truth],
        "mismatches": [],
    }
    report["missingNonRest"] = []
    report["unmatchedRest"] = []
    for read_index, truth_index in pairs:
        read, expected = reads[read_index], truth[truth_index]
        read_tab, truth_tab = _read_tab(read), _truth_tab(expected)
        if not read.get("beats"):
            report["unmatchedReads"].append(read.get("index"))
            continue
        if not truth_tab:
            report["restPairs"] += 1
            continue
        report["tabCompared"] += 1
        if Counter(fret for _string, fret in read_tab.elements()) == Counter(
            fret for _string, fret in truth_tab.elements()
        ):
            report["fretExact"] += 1
        if read_tab == truth_tab:
            report["tabExact"] += 1
        else:
            report["mismatches"].append({
                "readIndex": read.get("index"),
                "truthMeasure": expected.get("index"),
                "extra": [[string, fret] for (string, fret), count in (read_tab - truth_tab).items() for _ in range(count)],
                "missing": [[string, fret] for (string, fret), count in (truth_tab - read_tab).items() for _ in range(count)],
            })
    for truth_index in range(len(truth)):
        if truth_index in matched_truth:
            continue
        if _truth_tab(truth[truth_index]):
            report["missingNonRest"].append(truth[truth_index]["index"])
        else:
            report["unmatchedRest"].append(truth[truth_index]["index"])
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="模型读到的 TAB 与真值逐小节比对")
    parser.add_argument("--measures", required=True, help="out/<song>/measures 目录")
    parser.add_argument("--truth", required=True, help="tools/dump.mjs 导出的真值 JSON")
    parser.add_argument("--json-out", default=None, help="把完整报告写到这个文件")
    args = parser.parse_args(argv)

    reads = _reads(Path(args.measures))
    truth = _truth_measures(Path(args.truth))
    report = compare(reads, truth)

    checked = report["tabCompared"]
    print(f"模型读数：{report['displayedBars']} 个显示小节；真值：{report['truthMeasures']} 小节")
    rate = report["tabExact"] / checked * 100 if checked else 0.0
    print(f"逐小节比对：非空小节 {checked} 个，TAB（弦+品）完全一致 {report['tabExact']} 个（{rate:.1f}%）")
    if checked:
        print(f"  其中只比品数（忽略弦号）：{report['fretExact']} 个（{report['fretExact']/checked*100:.1f}%）")
    print(f"对齐到真值休止小节的读数：{report['restPairs']} 对")
    if report["mismatches"]:
        print(f"不一致：{len(report['mismatches'])} 处（前 10 条）")
        for item in report["mismatches"][:10]:
            print("  ", json.dumps(item, ensure_ascii=False))
    if report["missingNonRest"]:
        print(f"真值里非空、但没被覆盖到的小节：{report['missingNonRest']}")
    if report["unmatchedRest"]:
        print(f"没有单独读数对应的休止小节（多小节休止展开）：{len(report['unmatchedRest'])} 个")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"完整报告：{args.json_out}")
    return 0 if checked and report["tabExact"] == checked else 1


if __name__ == "__main__":
    raise SystemExit(main())
