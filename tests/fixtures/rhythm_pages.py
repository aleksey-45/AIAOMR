"""合成节奏图：给几何节奏的测试用。只画谱线、符头、符干、符尾、附点。"""

from __future__ import annotations

import numpy as np


def _disc(arr: np.ndarray, cx: float, cy: float, rx: float, ry: float) -> None:
    ys = np.arange(max(0, int(cy - ry) - 1), min(arr.shape[0], int(cy + ry) + 2))
    xs = np.arange(max(0, int(cx - rx) - 1), min(arr.shape[1], int(cx + rx) + 2))
    for y in ys:
        for x in xs:
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                arr[int(y), int(x)] = 0


def _ring(arr: np.ndarray, cx: float, cy: float, rx: float, ry: float, thickness: float = 2.0) -> None:
    """空心椭圆：画实心，再把中间抹回白色（谱线穿过符头的位置也要抹掉）。"""
    _disc(arr, cx, cy, rx, ry)
    ys = np.arange(max(0, int(cy - ry) - 1), min(arr.shape[0], int(cy + ry) + 2))
    xs = np.arange(max(0, int(cx - rx) - 1), min(arr.shape[1], int(cx + rx) + 2))
    for y in ys:
        for x in xs:
            if ((x - cx) / max(0.1, rx - thickness)) ** 2 + ((y - cy) / max(0.1, ry - thickness)) ** 2 <= 1.0:
                arr[int(y), int(x)] = 255


def _rect(arr: np.ndarray, x0: float, x1: float, y0: float, y1: float) -> None:
    arr[max(0, int(y0)) : int(y1), max(0, int(x0)) : int(x1)] = 0


def rhythm_measure(beats: list[dict], deg: int = 12, staff_top: int = 60, beat_gap: int | None = None) -> np.ndarray:
    """画一个小节。`beats` 里每项：kind=note/whole/rest，beams=0/1/2，dots=0/1。"""
    beat_gap = beat_gap or int(round(3.0 * deg))
    width = int(deg + beat_gap * len(beats) + deg)
    height = staff_top + 4 * deg + 3 * deg
    arr = np.full((height, width), 255, dtype=np.uint8)

    for line in range(5):
        y = staff_top + line * deg
        arr[y : y + 1, deg : width - deg] = 0
    for x in (deg, width - deg):
        arr[staff_top : staff_top + 4 * deg, x] = 0

    note_y = staff_top + 3 * deg
    positions = [deg + beat_gap * (i + 0.6) for i in range(len(beats))]
    stem_tops: list[float] = []
    for position, beat in zip(positions, beats):
        kind = beat.get("kind", "note")
        if kind == "rest":
            continue
        if kind == "whole":
            _ring(arr, position, note_y - 0.5 * deg, 0.65 * deg, 0.4 * deg)
            stem_tops.append(float("nan"))
            continue
        if kind == "half":
            _ring(arr, position, note_y - 0.5 * deg, 0.6 * deg, 0.38 * deg)
            stem_x = position + 0.5 * deg
            stem_top = note_y - 3.4 * deg
            arr[int(stem_top) : int(note_y) + 1, int(stem_x) : int(stem_x) + max(1, deg // 10)] = 0
            stem_tops.append(stem_top)
            if beat.get("dots"):
                _disc(arr, position + 1.25 * deg, note_y - 0.1 * deg, 0.16 * deg, 0.16 * deg)
            continue
        _disc(arr, position, note_y, 0.55 * deg, 0.38 * deg)
        stem_x = position + 0.5 * deg
        stem_top = note_y - 3.4 * deg
        arr[int(stem_top) : int(note_y) + 1, int(stem_x) : int(stem_x) + max(1, deg // 10)] = 0
        stem_tops.append(stem_top)
        if beat.get("dots"):
            _disc(arr, position + 1.25 * deg, note_y - 0.1 * deg, 0.16 * deg, 0.16 * deg)

    # 连梁：相邻两个都在 beamed 组里的音柱之间画粗横线
    index = 0
    while index < len(beats):
        count = int(beats[index].get("beams", 0))
        if count == 0:
            index += 1
            continue
        end = index
        while end + 1 < len(beats) and int(beats[end + 1].get("beams", 0)) == count:
            end += 1
        if end > index:
            for i in range(index, end):
                x0 = positions[i] + 0.5 * deg
                x1 = positions[i + 1] + 0.5 * deg
                for beam in range(count):
                    y = stem_tops[i] + beam * 0.9 * deg
                    _rect(arr, x0, x1 + 1, y, y + max(2, deg * 0.45))
        else:
            # 单个八分/十六分：画符尾（小钩）
            x = positions[index] + 0.5 * deg
            for beam in range(count):
                y = stem_tops[index] + beam * 0.9 * deg
                _rect(arr, x + 1, x + deg * 0.9, y, y + max(2, deg * 0.4))
        index = end + 1
    return arr
