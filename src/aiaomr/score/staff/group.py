"""归属：符头配符干、横梁段建图、组内顺序（`docs/spec-staff.md` SR-40..46）。

判据给的是零件：符干、横梁段、符头、符尾、附点。节奏型取决于它们的连接关系，这一层负责三件事：

- **符头配符干**：一个符干可以带多个符头（和弦）；配不上、或者实心符头没有符干 → abstain；
- **横梁段建图**：段的两端各接一根符干，连通块就是连梁组；每根符干的横梁条数 = **入射段条数**
  （不是"两干之间的行数"——那会把混合时值平均掉）；
- **组内顺序**：只有右段 = 组首，只有左段 = 组尾，两侧都有 = 中间（SR-42）。

没有符干的空心符头是**全音符**（SR-50），单独成拍。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...kernel.config import StaffConfig, load_staff_config
from .base import Finding
from .context import GeoContext


@dataclass
class NoteGlyph:
    """一个发声单位：一个符干 + 它带的符头，或者一个没有符干的全音符。"""

    x: float
    heads: list[Finding] = field(default_factory=list)
    stem: Finding | None = None
    beams: int = 0
    flags: int = 0
    group: int | None = None
    dots: int = 0

    @property
    def head_class(self) -> str | None:
        """同一个符干上的符头类别应一致（SR-24）；不一致返回 `None`。"""
        classes = {("hollow" if head.value == 1.0 else "filled") for head in self.heads}
        return classes.pop() if len(classes) == 1 else None


@dataclass
class Grouping:
    """一整个小节的归属结果；`abstains` 是 [(AR 编号, 细节)]。"""

    glyphs: list[NoteGlyph] = field(default_factory=list)
    abstains: list[tuple[str, dict]] = field(default_factory=list)


def _stem_root_distance(stem: Finding, head: Finding, max_pair: float) -> float:
    """符头中心到符干两端的最近距离（SR-40：按符干根端配对）。

    符头中心在符干左侧半个符头宽是常态（符干从符头右侧伸出），所以横向容差不能按"贴住符干"
    去卡，而是用配对距离上限 `pair_max_deg`。
    """
    center_x = (head.bbox[0] + head.bbox[2]) / 2
    center_y = (head.bbox[1] + head.bbox[3]) / 2
    if abs(center_x - max(stem.bbox[0], stem.bbox[2])) > max_pair:
        return float("inf")
    return min(abs(center_y - stem.bbox[1]), abs(center_y - stem.bbox[3]))


def group_notes(
    ctx: GeoContext,
    findings: dict[str, list[Finding]],
    staff: StaffConfig | None = None,
) -> Grouping:
    """把判据的零件组装成逐个发声单位，并标出归属上的问题。"""
    cfg = staff if staff is not None else load_staff_config()
    deg = ctx.deg
    max_pair = cfg.pair_max_deg * deg
    stems = sorted(findings.get("stem", []), key=lambda finding: finding.value)
    heads = list(findings.get("head", []))
    segments = list(findings.get("beam", []))
    flags = list(findings.get("flag", []))
    result = Grouping()

    # ---- 符头 → 符干（就近配对，允许多个符头共用一根符干：和弦）----------
    assignment: dict[int, list[Finding]] = {index: [] for index in range(len(stems))}
    orphans: list[Finding] = []
    for head in heads:
        best = None
        best_distance = float("inf")
        for index, stem in enumerate(stems):
            distance = _stem_root_distance(stem, head, max_pair)
            if distance < best_distance:
                best, best_distance = index, distance
        if best is None or best_distance > max_pair:
            orphans.append(head)
        else:
            assignment[best].append(head)

    for head in orphans:
        # 没有符干的空心符头 = 全音符（SR-50）；实心符头没符干说明配对错了。
        if head.value == 1.0:
            result.glyphs.append(
                NoteGlyph(x=(head.bbox[0] + head.bbox[2]) / 2, heads=[head], stem=None)
            )
        else:
            result.abstains.append(
                ("AR-03", {"head": [round(value, 1) for value in head.bbox]})
            )
    for index, stem in enumerate(stems):
        if not assignment[index]:
            result.abstains.append(("AR-03", {"stem": round(stem.value, 1)}))
            continue
        result.glyphs.append(
            NoteGlyph(x=stem.value, heads=assignment[index], stem=stem)
        )

    # ---- 横梁段建图：先把"逐对相邻符干"的段合并成真正的横梁线 ------------
    # 一对相邻符干之间会各出一段，同一条横梁线跨三根符干就会被切成两段；
    # 不合并的话中间那根符干会被数成"两条横梁"，二分音符/八分音符就串档了。
    lines = _merge_segments(segments, deg, cfg.beam_row_gap_deg)
    parent = list(range(len(stems)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        parent[find(first)] = find(second)

    incident: dict[int, int] = {index: 0 for index in range(len(stems))}
    tol = 0.6 * deg
    for line in lines:
        touched = [
            index for index, stem in enumerate(stems)
            if line.bbox[0] - tol <= stem.value <= line.bbox[2] + tol
        ]
        if not touched:
            result.abstains.append(("AR-11", {"segment": [round(value, 1) for value in line.bbox]}))
            continue
        for index in touched:
            incident[index] += 1
        for index in touched[1:]:
            union(touched[0], index)

    # ---- 组编号、每根符干的横梁条数、双声部检测 ----------------------------
    component_index: dict[int, int] = {}
    for index in range(len(stems)):
        root = find(index)
        component_index.setdefault(root, len(component_index))
    by_stem: dict[float, NoteGlyph] = {glyph.x: glyph for glyph in result.glyphs if glyph.stem is not None}
    for index, stem in enumerate(stems):
        glyph = by_stem.get(stem.value)
        if glyph is None:
            continue
        glyph.beams = incident[index]
        glyph.group = component_index[find(index)]
        glyph.flags = _nearest_flag(flags, stem.value)

    for first in range(len(stems)):
        for second in range(first + 1, len(stems)):
            if abs(stems[first].value - stems[second].value) <= 0.3 * deg:
                result.abstains.append(
                    ("AR-06", {"stems": [round(stems[first].value, 1), round(stems[second].value, 1)]})
                )

    # ---- 组内符头类别一致（SR-24/SR-44）----------------------------------
    groups: dict[int, set[str]] = {}
    for glyph in result.glyphs:
        if glyph.group is None:
            continue
        head_class = glyph.head_class
        if head_class is None:
            result.abstains.append(("AR-02", {"x": round(glyph.x, 1)}))
            continue
        groups.setdefault(glyph.group, set()).add(head_class)
    for group_id, classes in groups.items():
        if len(classes) > 1:
            result.abstains.append(("AR-04", {"group": group_id, "classes": sorted(classes)}))

    result.glyphs.sort(key=lambda glyph: glyph.x)
    return result


def _merge_segments(segments: list[Finding], deg: float, layer_gap_deg: float) -> list[Finding]:
    """把相邻符干对之间的段合并成连续的横梁线（同一层、水平相接）。"""
    lines: list[Finding] = []
    for segment in sorted(segments, key=lambda item: (item.bbox[1], item.bbox[0])):
        merged = False
        for line in lines:
            same_layer = abs(segment.bbox[1] - line.bbox[1]) <= layer_gap_deg * deg
            same_thickness = abs(
                (segment.bbox[3] - segment.bbox[1]) - (line.bbox[3] - line.bbox[1])
            ) <= 0.6 * deg
            touch = (
                segment.bbox[0] <= line.bbox[2] + 0.4 * deg
                and segment.bbox[2] >= line.bbox[0] - 0.4 * deg
            )
            if same_layer and same_thickness and touch:
                line.bbox = (
                    min(line.bbox[0], segment.bbox[0]),
                    min(line.bbox[1], segment.bbox[1]),
                    max(line.bbox[2], segment.bbox[2]),
                    max(line.bbox[3], segment.bbox[3]),
                )
                merged = True
                break
        if not merged:
            lines.append(
                Finding(
                    kind=segment.kind,
                    value=segment.value,
                    bbox=tuple(segment.bbox),
                    evidence=dict(segment.evidence),
                )
            )
    return lines


def _nearest_stem(stems: list[Finding], x: float | None) -> int | None:
    if x is None or not stems:
        return None
    return min(range(len(stems)), key=lambda index: abs(stems[index].value - x))


def _nearest_flag(flags: list[Finding], x: float) -> int:
    best = 0
    for flag in flags:
        if abs(flag.evidence.get("stem", -1e9) - x) <= 1.0:
            best = max(best, int(flag.value))
    return best
