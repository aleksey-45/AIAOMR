"""装配：把逐小节的读取结果拼成 IR（规格 §2.7 AS-01..AS-04）。

两件事：

- 多小节休止展开成 N 个空小节，并保留条数标记（AS-01）；
- 小节编号：IR 的 `index` 永远是连续的 1..N；`printed` 以印刷号优先、累加兜底（AS-03）。

反复、房子、跳转只记录不展开（AS-02），P1 里结构先留空。
"""

from __future__ import annotations

from datetime import datetime, timezone

from ...kernel.contracts import MeasureRead, Skeleton
from ...kernel.ir import Build, IR, Measure, Meta, Score, Source, Structure


def _default_meta() -> Meta:
    return Meta(
        provider="stub",
        model="stub",
        promptVersion="p0",
        schemaVersion="3.0",
        generatedAt=datetime.now(timezone.utc),
    )


def _default_source(class_: int) -> Source:
    return Source(**{"class": class_}, kind="image", files=[], inputSha256="")


def assemble(
    reads: list[MeasureRead],
    skeleton: Skeleton,
    alarms: list | None = None,
    source: Source | None = None,
    meta: Meta | None = None,
    structure: Structure | None = None,
    class_: int = 3,
) -> IR:
    """逐小节事实 + 骨架 + 报警 → IR。"""
    del alarms  # P1 只实现五条报警，终裁记录留到 P2
    measures: list[Measure] = []
    last_printed: int | None = None

    for read in reads:
        count = max(1, int(read.multiRest))
        printed = read.printed
        if count > 1:
            for offset in range(count):
                measures.append(
                    Measure(
                        index=len(measures) + 1,
                        printed=None if printed is None else printed + offset,
                        rest=True,
                        multiRest=count if offset == 0 else 1,
                        beats=[],
                    )
                )
            if printed is not None:
                last_printed = printed + count - 1
            continue

        if printed is None and last_printed is not None:
            printed = last_printed + 1
        if printed is not None:
            last_printed = printed
        measures.append(
            Measure(
                index=len(measures) + 1,
                printed=printed,
                rest=bool(read.unreadable),
                multiRest=1,
                beats=list(read.beats),
            )
        )

    score = Score(
        title=skeleton.title,
        artist=skeleton.artist,
        tabber="",
        tuning=list(skeleton.tuning),
        stringCount=skeleton.stringCount,
        timeSignatures=list(skeleton.timeSignatures),
        keySignatures=list(skeleton.keySignatures),
        tempos=list(skeleton.tempos),
        clefTranspose=skeleton.clefTranspose,
        fretCount=skeleton.fretCount,
    )
    return IR(
        meta=meta or _default_meta(),
        source=source or _default_source(class_),
        score=score,
        skeletonProvenance=skeleton.provenance,
        measures=measures,
        structure=structure or Structure(),
        judgements=[],
        build=None,
    )
