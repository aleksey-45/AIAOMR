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
    ctx = measure_context(
        arr, system, measure_box, deg,
        margin_deg=cfg.band_margin_deg if margin_deg is None else margin_deg,
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
