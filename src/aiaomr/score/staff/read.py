"""读谱编排：窗口 → 判据 → 归属 → 时值 → 拍格组织 → `MeasureRhythm`。

依据：`docs/spec-staff.md` §3（输出）、§7（时值判定）、§8（组织与和校验）、§9（abstain 编号）。

编排里**不做判断**：判断都在判据（`heads/stems/beams/dots/rests`）、归属（`group`）、
时值表（`duration`）与拍格（`organize`）里；这里只按顺序调用并把结果装进契约结构。
三条铁律从一开始就生效：不用横向间距推时值与 onset、拍格只作否决、判不准就 abstain。
"""

from __future__ import annotations

import numpy as np

from ...kernel.config import StaffConfig, load_staff_config
from ...kernel.contracts import (
    Abstain,
    MeasureBox,
    MeasureRhythm,
    RhythmBeat,
    System,
)
from ...kernel.ir import TimeSignature
from .beams import BeamCriterion, FlagCriterion
from .context import measure_context
from .dots import DotCriterion
from .duration import note_duration, rest_duration, ticks
from .group import Grouping, group_notes
from .heads import HeadCriterion
from .organize import organize
from .rests import RestBarCriterion, RestGlyphCriterion, RestRectCriterion
from .stems import StemCriterion


def _dots_by_head(findings: dict) -> dict[tuple, int]:
    """附点结论按锚定的符头分组：key 是符头 bbox 取整，值是这个符头上的附点个数。"""
    out: dict[tuple, int] = {}
    for dot in findings.get("dot", []):
        if dot.evidence.get("anchor") != "head":
            continue
        key = tuple(round(float(value), 1) for value in dot.evidence.get("anchor_bbox", ()))
        out[key] = max(out.get(key, 0), int(dot.evidence.get("dots", 1)))
    return out


def _glyph_beats(
    grouping: Grouping,
    dots_map: dict[tuple, int],
) -> tuple[list[RhythmBeat], list[tuple[str, dict]]]:
    beats: list[RhythmBeat] = []
    problems: list[tuple[str, dict]] = list(grouping.abstains)
    for glyph in grouping.glyphs:
        head_class = glyph.head_class
        has_stem = glyph.stem is not None
        beams = glyph.beams if has_stem else 0
        if has_stem and beams == 0 and glyph.flags:
            beams = glyph.flags  # 单音符的符尾按"横梁条数"同口径参与时值判定（SR-31/52/53）
        duration = note_duration(head_class, has_stem, beams)
        if duration is None:
            problems.append(("AR-02", {"x": round(glyph.x, 1), "heads": len(glyph.heads)}))
        dots = 0
        for head in glyph.heads:
            key = tuple(round(float(value), 1) for value in head.bbox)
            dots = max(dots, dots_map.get(key, 0))
        evidence = {
            "head": head_class,
            "beams": beams,
            "group": glyph.group,
            "heads": len(glyph.heads),
            "stem": has_stem,
        }
        beats.append(
            RhythmBeat(
                x=float(glyph.x),
                kind="note",
                duration=duration,
                dots=dots,
                noteCount=len(glyph.heads),
                head=head_class,
                beams=beams,
                group=glyph.group,
                confidence=1.0 if duration is not None else 0.0,
                evidence=evidence,
            )
        )
    return beats, problems


def _rest_beats(findings: dict) -> tuple[list[RhythmBeat], list[tuple[str, dict]]]:
    beats: list[RhythmBeat] = []
    problems: list[tuple[str, dict]] = []
    for key in ("rest_rect", "rest_glyph"):
        for rest in findings.get(key, []):
            category = rest.evidence.get("category", "")
            duration = rest_duration(category)
            if duration is None:
                problems.append(("AR-08", {"category": category}))
                continue
            beats.append(
                RhythmBeat(
                    x=float((rest.bbox[0] + rest.bbox[2]) / 2),
                    kind="rest",
                    duration=duration,
                    noteCount=0,
                    confidence=1.0,
                    evidence={"category": category,
                              "bbox": [round(value, 1) for value in rest.bbox]},
                )
            )
    return beats, problems


def _center(finding) -> float:
    return float((finding.bbox[0] + finding.bbox[2]) / 2)


def _own_window(
    findings: dict[str, list],
    ctx,
    measure_box: MeasureBox,
    cfg: StaffConfig,
) -> dict[str, list]:
    """只保留"属于本小节"的判据结论（SR-14）。

    窗口左右留了 `measure_margin_deg` 的余量（否则边界上的符干会被切掉），所以归属不能按
    窗口边界算，而是按**内容小节框**算：符号中心落在 `[x0, x1]` 才算本小节的。
    """
    left = measure_box.x0 - ctx.left
    right = measure_box.x1 - ctx.left

    band = 4.0 * ctx.deg  # 谱表高（五条线之间是 4 个 deg）
    barline_tol = max(6.0, 0.8 * ctx.deg)
    out: dict[str, list] = {}
    for kind, items in findings.items():
        kept = []
        for finding in items:
            if kind != "rest_bar":
                center = _center(finding)
                if center < left or center > right:
                    continue
            kept.append(finding)
        out[kind] = kept

    # 窗口外扩后，小节线会整个落在窗口里；它和符干一样是竖线，靠"长度≈谱表高、
    # 贴着小节边界"两个条件把它摘掉，别让它变成一根没有符头的假符干。
    stems = out.get("stem", [])
    out["stem"] = [
        stem for stem in stems
        if not (
            min(abs(stem.value - left), abs(stem.value - right)) <= barline_tol
            and abs((stem.bbox[3] - stem.bbox[1]) - band) <= 0.4 * ctx.deg
        )
    ]
    # 贴着小节线的一小块墨（小节线的残余、连音线起点）会被当成休止字形；真实记谱里
    # 第一个符号离小节线至少有一个符头的距离，所以贴着边界的一律不算休止。
    for kind in ("rest_rect", "rest_glyph"):
        out[kind] = [
            rest for rest in out.get(kind, [])
            if min(abs(_center(rest) - left), abs(right - _center(rest))) > barline_tol
        ]
    return out


def _drop_rests_on_notes(findings: dict[str, list]) -> None:
    """休止符不能和音符/符干占同一块位置（真页面上符头被谱线切成的小矩形会冒充休止符）。"""
    occupied = list(findings.get("head", [])) + list(findings.get("stem", []))
    for kind in ("rest_rect", "rest_glyph"):
        kept = []
        for rest in findings.get(kind, []):
            cx = (rest.bbox[0] + rest.bbox[2]) / 2
            cy = (rest.bbox[1] + rest.bbox[3]) / 2
            clash = False
            for item in occupied:
                if item.bbox[0] - 2 <= cx <= item.bbox[2] + 2 and item.bbox[1] - 2 <= cy <= item.bbox[3] + 2:
                    clash = True
                    break
            if not clash:
                kept.append(rest)
        findings[kind] = kept


def _abstains(problems: list[tuple[str, dict]], index: int) -> list[Abstain]:
    merged: dict[str, dict] = {}
    for reason, detail in problems:
        merged.setdefault(reason, {"items": []})["items"].append(detail)
    return [Abstain(reason=reason, measure=index, detail=detail) for reason, detail in merged.items()]


def read_measure(
    arr: np.ndarray,
    system: System,
    measure_box: MeasureBox,
    deg: float,
    signature: TimeSignature | None = None,
    expected_ticks: int | None = None,
    margin_deg: float | None = None,
    line_runs: list[tuple[int, int]] | None = None,
    staff: StaffConfig | None = None,
) -> MeasureRhythm:
    """读一个小节。`signature` 是该小节生效的拍号（骨架层给），拍格只用来否决（SR-02）。"""
    cfg = staff if staff is not None else load_staff_config()
    index = measure_box.index
    # 谱号/调号/拍号是骨架层（skeleton）的职责，由它先读好；读小节内容的窗口**绝不能**
    # 把它们截进来再过滤（SR-13b）。所以系统第一个小节的窗口左界从小节框或 headerX1 里取大者。
    content_x0 = measure_box.x0
    first_measure = bool(system.measures) and measure_box.index == system.measures[0].index
    if first_measure and system.headerX1 > system.headerX0 and system.headerX1 <= measure_box.x1:
        content_x0 = max(content_x0, system.headerX1)
    content_box = measure_box
    if content_x0 != measure_box.x0:
        content_box = MeasureBox(
            index=measure_box.index,
            printed=measure_box.printed,
            x0=content_x0,
            x1=measure_box.x1,
            width=measure_box.x1 - content_x0,
        )
    ctx = measure_context(
        arr, system, content_box, deg,
        margin_deg=cfg.band_margin_deg if margin_deg is None else margin_deg,
        x_margin_deg=cfg.measure_margin_deg,
        line_runs=line_runs,
    )
    if ctx.dark.size == 0:
        return MeasureRhythm(
            index=index, status="unknown", deg=deg,
            abstains=_abstains([("AR-10", {"width": ctx.width, "height": ctx.height})], index),
        )

    findings: dict[str, list] = {}
    findings["stem"] = StemCriterion(cfg).detect(ctx, findings)
    findings["beam"] = BeamCriterion(cfg).detect(ctx, findings)
    findings["flag"] = FlagCriterion(cfg).detect(ctx, findings)
    findings["head"] = HeadCriterion(cfg).detect(ctx, findings)
    findings["dot"] = DotCriterion(cfg).detect(ctx, findings)
    findings["rest_bar"] = RestBarCriterion(cfg).detect(ctx, findings)
    findings["rest_rect"] = RestRectCriterion(cfg).detect(ctx, findings)
    findings["rest_glyph"] = RestGlyphCriterion(cfg).detect(ctx, findings)
    findings = _own_window(findings, ctx, content_box, cfg)
    _drop_rests_on_notes(findings)

    # 多小节休止条：整小节一条休止（条数由印刷数字/模型给，本层只说"这是休止条"）。
    if findings["rest_bar"] and not findings["rest_rect"] and not findings["rest_glyph"]:
        return MeasureRhythm(
            index=index, status="ok", deg=deg, ticks=32,
            beats=[RhythmBeat(x=float(ctx.left + ctx.width / 2), kind="rest",
                              duration="whole", noteCount=0,
                              evidence={"category": "rest_bar"})],
        )

    dots_map = _dots_by_head(findings)
    grouping = group_notes(ctx, findings, cfg)
    note_beats, note_problems = _glyph_beats(grouping, dots_map)
    rest_beats, rest_problems = _rest_beats(findings)
    beats = sorted(note_beats + rest_beats, key=lambda beat: beat.x)
    problems = note_problems + rest_problems

    if not beats:
        ink = int(ctx.beam_dark.sum())
        center = float(ctx.left + ctx.width / 2)
        # 只有"几乎一点墨都没有"才允许判整小节休止（SR-57）；全音符的空心圈也算墨迹。
        if ink < max(4.0, 0.05 * deg * deg):
            beats = [RhythmBeat(x=center, kind="rest", duration="whole", noteCount=0,
                                evidence={"category": "empty-bar"})]
        else:
            problems.append(("AR-02", {"ink": ink}))

    organization = organize(beats, signature=signature, expected=expected_ticks)
    problems.extend(organization.abstains)
    total = sum(ticks(beat.duration, beat.dots) or 0 for beat in beats)
    abstains = _abstains(problems, index)
    if abstains or organization.status != "ok":
        return MeasureRhythm(index=index, status="unknown", beats=beats,
                             abstains=abstains, ticks=total, deg=deg)
    return MeasureRhythm(index=index, status="ok", beats=beats,
                         ticks=organization.ticks, deg=deg)


def read_system(
    arr: np.ndarray,
    system: System,
    deg: float,
    signatures_by_measure: dict[int, TimeSignature] | None = None,
    line_runs: list[tuple[int, int]] | None = None,
    staff: StaffConfig | None = None,
) -> list[MeasureRhythm]:
    """读一个系统里的所有小节，按小节号顺序返回。"""
    result: list[MeasureRhythm] = []
    for box in system.measures:
        signature = None if signatures_by_measure is None else signatures_by_measure.get(box.index)
        result.append(read_measure(arr, system, box, deg, signature=signature,
                                   line_runs=line_runs, staff=staff))
    return result


def read_page(
    arr: np.ndarray,
    system: System,
    deg: float,
    signatures_by_measure: dict[int, TimeSignature] | None = None,
) -> list[MeasureRhythm]:
    """读一个系统的入口（与规范 §12.1 的 `read_page/read_system/read_measure` 对应）。"""
    return read_system(arr, system, deg, signatures_by_measure)
