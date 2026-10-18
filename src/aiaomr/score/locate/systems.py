"""定位层的系统切分（规格 §2.1 R-01..R-08，R-09 属于视频输入，另实现）。

输入是一张已转成灰度的页面数组，输出 `System` 列表：每个系统记下五线谱带、
TAB 带、TAB 各弦的 y 坐标。这里**不**做任何语义判断：不认音符、不认谱号。

两条关键经验（都来自旧项目，见 `docs/spec-v3.md` §1.7）：

- 阈值是 deg（谱线间距）的倍数，不是绝对像素；
- 短末行不能按整页宽度判断覆盖率，要看它自己的墨迹宽度。
"""

from __future__ import annotations

import numpy as np

from ...kernel.contracts import StaffLine, System

# 两行算同一组谱线的最大间隔（像素）。谱线本身是 1~3 px，间断只可能来自抗锯齿。
_ROW_MERGE_GAP = 2
# 五条谱线等距容差。
_SPACING_TOL = 0.25


def adaptive_cut(arr: np.ndarray) -> float:
    """行分割的灰度阈值取页面自己亮度的低分位，不用固定 128。

    旧项目的教训：视频截图里的谱线可能只有 150 左右，而播放器界面比它还黑；
    拿 128 去切，切掉的是界面，留下的是噪声。
    """
    return float(max(60.0, min(200.0, np.percentile(arr, 80) - 60.0)))


def row_groups(mask: np.ndarray, frac: float, axis: int = 1) -> list[int]:
    """沿 `axis` 求覆盖率超过 `frac` 的连续行/列，返回每组中心。"""
    counts = mask.sum(axis=axis)
    span = mask.shape[axis]
    indices = np.flatnonzero(counts > frac * span)
    groups: list[list[int]] = []
    for position in indices:
        position = int(position)
        if groups and position - groups[-1][-1] <= _ROW_MERGE_GAP:
            groups[-1].append(position)
        else:
            groups.append([position])
    return [int(np.mean(group)) for group in groups]


def staff_line_runs(
    arr: np.ndarray,
    frac: float = 0.60,
    max_thickness: int | None = None,
) -> list[tuple[int, int]]:
    """返回谱线的**行 run**（起止行号，含两端），按 y 升序（R-10）。

    只给中心行是不够的：读谱层抹线时必须抹掉整条线厚，否则上下两条边沿会留在图里，
    被横梁判据当成两条横梁（真页面实测会把整小节读成十六分）。
    覆盖率用"墨迹像素 / 该行墨迹跨度"，所以短末行（只画到页面三成宽）也能算进来；
    厚度按"中位谱线厚度的倍数"过滤，多小节休止条、黑边、播放器进度条都会被丢掉。
    """
    cut = adaptive_cut(arr)
    dark = arr < cut
    height, width = dark.shape
    counts = dark.sum(axis=1)

    first = np.argmax(dark, axis=1)
    last = width - 1 - np.argmax(dark[:, ::-1], axis=1)
    extents = np.where(counts > 0, last - first + 1, 0)
    coverage = np.divide(counts, extents, out=np.zeros(height), where=extents > 0)

    # 一条真实谱线的横向跨度至少要有页面的 10%：挡掉页眉文字、单个音符。
    min_extent = max(20, int(width * 0.10))
    line_rows = (counts > 0) & (extents >= min_extent) & (coverage > frac)

    runs: list[list[int]] = []
    for row in np.flatnonzero(line_rows):
        row = int(row)
        if runs and row - runs[-1][-1] <= _ROW_MERGE_GAP:
            runs[-1].append(row)
        else:
            runs.append([row])
    if not runs:
        return []

    # 厚度上限按"相邻线组间距的下四分位"定，不用绝对像素：正常谱线 1~3 px，
    # 多小节休止条会和谱线合成一个 ~24 px 的组，而黑边、播放条通常 40 px 以上。
    centers = [float(np.mean(run)) for run in runs]
    gaps = np.diff(centers) if len(centers) > 1 else np.array([60.0])
    limit = max_thickness or max(6, int(round(2.5 * float(np.percentile(gaps, 25)))))
    return [(run[0], run[-1]) for run in runs if len(run) <= limit]


def staff_lines(
    arr: np.ndarray,
    frac: float = 0.60,
    max_thickness: int | None = None,
) -> list[int]:
    """返回谱线中心的 y 坐标（含五线谱与 TAB 线，按 y 升序）。"""
    return [
        int(round((top + bottom) / 2))
        for top, bottom in staff_line_runs(arr, frac=frac, max_thickness=max_thickness)
    ]


def _uniform_spacing(lines: list[int], start: int, count: int, tol: float = _SPACING_TOL) -> float | None:
    """`lines[start:start+count]` 是否等距；是则返回间距。"""
    if start + count > len(lines):
        return None
    gaps = [lines[start + k + 1] - lines[start + k] for k in range(count - 1)]
    median = float(np.median(gaps))
    if median <= 0:
        return None
    if all(abs(gap - median) <= tol * median for gap in gaps):
        return median
    return None


def pair_systems(
    lines: list[int],
    page_width: int,
    min_w: int,
    extents: list[int] | None = None,
) -> list[tuple[int, int, int, int, int]]:
    """把等距的五线谱线组与它下方的 TAB 线组配对。

    返回 `(note_top, note_bottom, tab_top, tab_bottom, tab_count)`，坐标是 y。
    配对条件：TAB 线组与谱线组的纵向间隔在 2–20 倍 deg 之间，TAB 线距 > 1.2 倍谱线距。
    `min_w` 是系统最小横向墨迹宽度：给了 `extents` 就按它过滤，短末行不会被误杀。
    """
    systems: list[tuple[int, int, int, int, int]] = []
    index = 0
    while index + 4 < len(lines):
        note_sp = _uniform_spacing(lines, index, 5)
        if note_sp is None:
            index += 1
            continue
        note_top = lines[index]
        note_bottom = lines[index + 4]

        found = None
        cursor = index + 5
        while cursor < len(lines):
            gap = lines[cursor] - note_bottom
            if gap > 20 * note_sp:
                break
            for tab_count in (4, 5, 6):
                tab_sp = _uniform_spacing(lines, cursor, tab_count)
                if tab_sp is None or tab_sp <= 1.2 * note_sp:
                    continue
                if 2 * note_sp <= gap <= 20 * note_sp:
                    found = (cursor, tab_count, tab_sp)
                    break
            if found is not None:
                break
            cursor += 1

        if found is None:
            index += 1
            continue

        cursor, tab_count, _tab_sp = found
        tab_top = lines[cursor]
        tab_bottom = lines[cursor + tab_count - 1]
        if extents is not None:
            width = min(extents[lines[index]], extents[lines[cursor]])
            if width < min_w:
                index += 1
                continue
        systems.append((note_top, note_bottom, tab_top, tab_bottom, tab_count))
        index = cursor + tab_count
    return systems


def find_systems(
    arr: np.ndarray,
    page_width: int,
    page_index: int = 0,
    min_w: int | None = None,
    frac: float = 0.60,
) -> list[System]:
    """整页 → `System` 列表。`min_w` 默认取页宽的 10%。"""
    if arr.ndim != 2:
        raise ValueError("find_systems 需要二维灰度数组")
    if min_w is None:
        min_w = max(20, int(page_width * 0.10))

    runs = staff_line_runs(arr, frac=frac)
    lines = [int(round((top + bottom) / 2)) for top, bottom in runs]
    if not lines:
        return []

    dark = arr < adaptive_cut(arr)
    width = arr.shape[1]
    first = np.argmax(dark, axis=1)
    last = width - 1 - np.argmax(dark[:, ::-1], axis=1)
    extents = (last - first + 1).tolist()

    systems: list[System] = []
    for system_id, (note_top, note_bottom, tab_top, tab_bottom, tab_count) in enumerate(
        pair_systems(lines, page_width, min_w, extents=extents), start=1
    ):
        # 五线谱那 5 条的"行 run"交给读谱层：抹线要按整条线厚抹（R-10、SR-11）。
        note_start = lines.index(int(note_top))
        staff_lines_runs = [
            StaffLine(top=float(runs[index][0]), bottom=float(runs[index][1]),
                      center=float(lines[index]))
            for index in range(note_start, min(note_start + 5, len(runs)))
        ]
        # TAB 各弦的 y 坐标，顺序自上而下（对应 stringCount..1，提示词按这个顺序用）。
        tab_start = lines.index(int(tab_top))
        tab_lines = [float(y) for y in lines[tab_start : tab_start + tab_count]]
        systems.append(
            System(
                id=system_id,
                page=page_index,
                y0=float(note_top),
                y1=float(note_bottom),
                tabY0=float(tab_top),
                tabY1=float(tab_bottom),
                tabLines=tab_lines,
                staffLines=staff_lines_runs,
                measures=[],
                headerX0=0.0,
                headerX1=float(page_width),
            )
        )
    return systems
