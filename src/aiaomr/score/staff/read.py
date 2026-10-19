"""读谱编排：窗口 → 判据 → 归属（暂用原型）→ 时值 → 拍内和校验 → `MeasureRhythm`。

依据：`docs/spec-staff.md` §3（输出）、§7（时值判定）、§8（组织与和校验）、§9（abstain 编号）。

任务 0 只把编排和接口立起来，判据仍然是原型（符干 + 横梁/符尾条数 + 附点），
符头类别、休止三组、横梁左右延伸建图分别在任务 2、3 补齐。三条铁律从一开始就生效：
不用横向间距推时值与 onset、拍格只作否决、判不准就 abstain。
"""

from __future__ import annotations

import numpy as np

from ...kernel.contracts import (
    Abstain,
    MeasureBox,
    MeasureRhythm,
    RhythmBeat,
    System,
)
from .beams import BeamCriterion, FlagCriterion
from .context import measure_context
from .dots import DotCriterion
from .rests import RestBarCriterion
from .stems import StemCriterion

# 1/32 拍为 1 tick（四分音符 = 8）。
TICKS = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2, "32nd": 1}
# 横梁/符尾条数 → 时值。
DURATION_BY_BEAMS = {0: "quarter", 1: "eighth", 2: "16th", 3: "32nd"}


def _nearest_stem(stems, x: float):
    if not stems:
        return None
    return min(stems, key=lambda stem: abs(stem.value - x))


def _abstain(reason: str, measure: int, beat: int | None = None, **detail) -> Abstain:
    return Abstain(reason=reason, measure=measure, beat=beat, detail=detail)


def read_measure(
    arr: np.ndarray,
    system: System,
    measure_box: MeasureBox,
    deg: float,
    expected_ticks: int | None = None,
    margin_deg: float | None = None,
    line_runs: list[tuple[int, int]] | None = None,
) -> MeasureRhythm:
    """读一个小节。`expected_ticks` 是该小节生效拍号的 tick 数，来自骨架层。

    `margin_deg` 不给时取 `cfg.staff.band_margin_deg`（窗口余量同样只许从参数表来）。
    """
    index = measure_box.index
    ctx = measure_context(
        arr, system, measure_box, deg,
        margin_deg=margin_deg, line_runs=line_runs,
    )
    if ctx.dark.size == 0:
        return MeasureRhythm(index=index, status="unknown", deg=deg,
                             abstains=[_abstain("AR-10", index, width=ctx.width, height=ctx.height)])

    findings: dict[str, list] = {}
    for criterion in (StemCriterion(),):
        findings[criterion.name] = criterion.detect(ctx, findings)
    stems = findings["stem"]

    if not stems:
        if RestBarCriterion().detect(ctx, findings):
            return MeasureRhythm(
                index=index, status="ok", deg=deg, ticks=TICKS["whole"],
                beats=[RhythmBeat(x=float(ctx.left + ctx.width / 2), kind="rest",
                                  duration="whole", noteCount=0,
                                  evidence={"detected": "rest_bar"})],
            )
        ink = int(ctx.beam_dark.sum())
        center = float(ctx.left + ctx.width / 2)
        # 只有"几乎一点墨都没有"才允许判整小节休止（SR-57）：全音符的空心圈也在墨迹里，
        # 阈值放高会把它误读成休止，静默写出错误时值。
        if ink < max(4.0, 0.05 * deg * deg):
            return MeasureRhythm(
                index=index, status="ok", deg=deg, ticks=TICKS["whole"],
                beats=[RhythmBeat(x=center, kind="rest", duration="whole", noteCount=0,
                                  evidence={"detected": "empty-bar"})],
            )
        # 有墨迹却没有符干、也没有休止条：可能是全音符，也可能是没认出来的东西。
        return MeasureRhythm(
            index=index, status="unknown", deg=deg,
            abstains=[_abstain("AR-02", index, ink=ink)],
        )

    findings["beam"] = BeamCriterion().detect(ctx, findings)
    findings["flag"] = FlagCriterion().detect(ctx, findings)
    findings["dot"] = DotCriterion().detect(ctx, findings)

    beam_count: dict[float, int] = {}
    for beam in findings["beam"]:
        for key in (beam.bbox[0], beam.bbox[2]):
            beam_count[key] = max(beam_count.get(key, 0), int(beam.value))

    flags: dict[float, int] = {}
    for flag in findings["flag"]:
        stem = _nearest_stem(stems, flag.bbox[0] - 1)
        if stem is not None:
            flags[stem.value] = max(flags.get(stem.value, 0), int(flag.value))

    dots: set[float] = set()
    for dot in findings["dot"]:
        stem = _nearest_stem(stems, (dot.bbox[0] + dot.bbox[2]) / 2 - 0.6 * deg)
        if stem is not None:
            dots.add(stem.value)

    beats: list[RhythmBeat] = []
    for stem in stems:
        count = beam_count.get(stem.value, 0) or flags.get(stem.value, 0)
        beats.append(
            RhythmBeat(
                x=float(ctx.left + stem.value),
                kind="note",
                duration=DURATION_BY_BEAMS.get(count),
                dots=1 if stem.value in dots else 0,
                beams=count,
                evidence={"stem_top": stem.bbox[1], "stem_bottom": stem.bbox[3]},
            )
        )

    # SR-62：时值之和必须等于拍号；不等就整小节 abstain，禁止调时值去凑。
    if expected_ticks is None:
        return MeasureRhythm(index=index, status="unknown", beats=beats, deg=deg,
                             abstains=[_abstain("AR-09", index)])
    total = sum(
        int(round(TICKS[beat.duration] * (1.5 if beat.dots == 1 else 1.75 if beat.dots == 2 else 1.0)))
        for beat in beats if beat.duration is not None
    )
    missing = [beat for beat in beats if beat.duration is None]
    if missing or total != expected_ticks:
        return MeasureRhythm(
            index=index, status="unknown", beats=beats, deg=deg,
            abstains=[_abstain("AR-05", index, claimed=total, expected=expected_ticks)],
        )
    return MeasureRhythm(index=index, status="ok", beats=beats, ticks=total, deg=deg)


def read_system(
    arr: np.ndarray,
    system: System,
    deg: float,
    expected_ticks_by_measure: dict[int, int] | None = None,
    line_runs: list[tuple[int, int]] | None = None,
) -> list[MeasureRhythm]:
    """读一个系统里的所有小节，按小节号顺序返回。"""
    result: list[MeasureRhythm] = []
    for box in system.measures:
        expected = None if expected_ticks_by_measure is None else expected_ticks_by_measure.get(box.index)
        result.append(read_measure(arr, system, box, deg, expected, line_runs=line_runs))
    return result


def read_page(
    arr: np.ndarray,
    system: System,
    deg: float,
    expected_ticks_by_measure: dict[int, int] | None = None,
) -> list[MeasureRhythm]:
    """读一个系统的入口（与规范 §12.1 的 `read_page/read_system/read_measure` 对应）。"""
    return read_system(arr, system, deg, expected_ticks_by_measure)
