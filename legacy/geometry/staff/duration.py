"""时值判定表（`docs/spec-staff.md` SR-50..57）。

纯函数：输入是符号类别（符头空心/实心、有没有符干、横梁/符尾条数、附点个数），
输出是时值名与 tick 数。不读像素，不读拍号，不做任何猜测；判不出返回 `None`。
"""

from __future__ import annotations

# 1/32 拍为 1 tick（四分音符 = 8）。
TICKS = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2, "32nd": 1}
# 实心符头的横梁/符尾条数 → 时值（SR-52/53）。
DURATION_BY_BEAMS = {0: "quarter", 1: "eighth", 2: "16th", 3: "32nd"}
# 附点倍数（SR-55）。
DOT_FACTORS = {0: 1.0, 1: 1.5, 2: 1.75}


def note_duration(head: str | None, has_stem: bool, beams: int) -> str | None:
    """按 SR-50..53 判一个音符的时值；判不出返回 `None`（调用方 abstain）。"""
    if head == "hollow":
        return "half" if has_stem else "whole"
    if head == "filled":
        if not has_stem:
            return None  # 实心符头必须有符干；没有说明配对出了错
        return DURATION_BY_BEAMS.get(beams)
    return None


def rest_duration(category: str) -> str | None:
    """休止符类别（`rest_whole` 或 `whole`）→ 时值名。"""
    name = category.removeprefix("rest_")
    return name if name in TICKS else None


def ticks(duration: str | None, dots: int = 0) -> int | None:
    """时值 + 附点 → tick 数；时值未知返回 `None`。"""
    if duration is None:
        return None
    factor = DOT_FACTORS.get(dots)
    if factor is None:
        return None
    return int(round(TICKS[duration] * factor))
