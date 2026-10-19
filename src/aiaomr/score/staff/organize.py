"""拍格与三条否决（`docs/spec-staff.md` §8，SR-60..62）。

三条铁律里的第二条在这里落地：**拍号与拍格是装配时的隐含条件，不是切图依据**。它只做三件事：

- 连梁组的边界必须落在拍组边界上（4/4 是一个四分，6/8 是一个附点四分）；
- 从左到右累加各拍 tick，任一点不得超过小节总 tick；
- 累加必须等于该小节拍号。

三条都是"否决权"：写得出来的结论必须同时满足；不满足就整小节 unknown（带 AR 编号），
**禁止**调整某个音符的时值去凑。这里不使用任何横向间距信息（SR-01）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...kernel.contracts import RhythmBeat
from ...kernel.ir import TimeSignature
from .duration import ticks


@dataclass
class Organization:
    """组织结果：状态、总 tick、abstain 列表 [(AR 编号, 细节)]。"""

    status: str
    ticks: int = 0
    abstains: list[tuple[str, dict]] = field(default_factory=list)


def beat_group_ticks(signature: TimeSignature | None) -> int | None:
    """拍组（连梁分组单位）的 tick 数；不支持的拍号返回 `None`。

    4/4、3/4、2/4 → 一个四分（8）；6/8、9/8、12/8 → 三个八分（12）；
    2/2、3/2 → 一个二分（16）。其余（5/8、7/8、混合拍号）本版不支持（AR-09）。
    """
    if signature is None:
        return None
    key = (signature.beats, signature.beatType)
    # 本规范只保证这几种拍号（spec-staff §8.1）；5/8、7/8、混合拍号一律 abstain（AR-09）。
    if key not in _SUPPORTED:
        return None
    return _SUPPORTED[key]


# 拍号 → 拍组 tick 数（4/4、3/4、2/4 一个四分；6/8、9/8、12/8 三个八分；2/2、3/2 一个二分）。
_SUPPORTED: dict[tuple[int, int], int] = {
    (4, 4): 8,
    (3, 4): 8,
    (2, 4): 8,
    (6, 8): 12,
    (9, 8): 12,
    (12, 8): 12,
    (2, 2): 16,
    (3, 2): 16,
}


def expected_ticks(signature: TimeSignature) -> int:
    return int(round(signature.beats * 32 / signature.beatType))


def organize(
    beats: list[RhythmBeat],
    signature: TimeSignature | None = None,
    expected: int | None = None,
) -> Organization:
    """按 SR-60..62 判这一小节是否成立。`beats` 必须按 x 升序。"""
    if expected is None and signature is not None:
        expected = expected_ticks(signature)
    if expected is None:
        return Organization(status="unknown", abstains=[("AR-09", {})])

    abstains: list[tuple[str, dict]] = []
    missing = [
        (position, beat.x) for position, beat in enumerate(beats, start=1)
        if ticks(beat.duration, beat.dots) is None
    ]
    if missing:
        abstains.append(("AR-02", {"missing": [list(item) for item in missing]}))

    # 累加不得越界（SR-61），并记录每个连梁组的起止累计值
    total = 0
    group_spans: dict[int, list[int]] = {}
    for beat in beats:
        beat_ticks = ticks(beat.duration, beat.dots)
        if beat_ticks is None:
            continue
        if beat.group is not None:
            span = group_spans.setdefault(beat.group, [total, total])
            span[1] = total + beat_ticks
        total += beat_ticks
        if total > expected:
            abstains.append(("AR-05", {"overflow": total, "expected": expected}))
            break
    if total != expected:
        abstains.append(("AR-05", {"claimed": total, "expected": expected}))

    # 连梁组边界必须落在拍组边界上（SR-60）。只约束**连梁组**（一串音符被横梁连起来），
    # 单个音符本来就可以落在任何合法拍位上（附点四分从"第三拍后半"开始是正常的）。
    group_ticks = beat_group_ticks(signature)
    group_sizes: dict[int, int] = {}
    for beat in beats:
        if beat.group is not None:
            group_sizes[beat.group] = group_sizes.get(beat.group, 0) + 1
    if group_ticks:
        for group_id, (start, end) in sorted(group_spans.items()):
            if group_sizes.get(group_id, 0) < 2:
                continue
            if start % group_ticks or end % group_ticks:
                abstains.append(
                    ("AR-04", {"group": group_id, "start": start, "end": end,
                               "beatGroup": group_ticks})
                )

    if abstains:
        return Organization(status="unknown", ticks=total, abstains=abstains)
    return Organization(status="ok", ticks=total)
