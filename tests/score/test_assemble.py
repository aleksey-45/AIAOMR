"""装配的测试（规格 §2.7 AS-01/AS-03；计划任务 10）。"""

from __future__ import annotations

from aiaomr.kernel.contracts import MeasureRead, Skeleton
from aiaomr.kernel.ir import Beat, Evidence, Note, SkeletonProvenance, TimeSignature
from aiaomr.score.assemble.assemble import assemble

EVIDENCE = Evidence(system=1, crop=[0, 0, 10, 10], call="c1")


def skeleton() -> Skeleton:
    return Skeleton(
        timeSignatures=[TimeSignature(measure=1, beats=4, beatType=4)],
        keySignatures=[],
        tempos=[],
        tuning=[28, 33, 38, 43],
        stringCount=4,
        title="t",
        artist="",
        provenance=SkeletonProvenance(
            timeSignatures="read", tuning="read", keySignatures="defaulted",
            tempos="defaulted", title="filename", artist="empty",
        ),
    )


def read(index: int, multi_rest: int = 1, printed: int | None = None,
         unreadable: bool = False) -> MeasureRead:
    beats = [] if unreadable or multi_rest > 1 else [
        Beat(duration="whole", dots=0, rest=True, notes=[], prov="read", evidence=EVIDENCE)
    ]
    return MeasureRead(index=index, beats=beats, unreadable=unreadable,
                       printed=printed, multiRest=multi_rest)


def test_multi_rest_expands_to_n_empty_measures() -> None:
    ir = assemble([read(1, multi_rest=3)], skeleton())

    assert len(ir.measures) == 3
    assert all(measure.rest for measure in ir.measures)
    assert ir.measures[0].multiRest == 3
    assert ir.measures[1].multiRest == 1


def test_measure_count_equals_actual_length() -> None:
    ir = assemble([read(1), read(2)], skeleton())

    assert len(ir.measures) == 2
    # measureCount 是计算字段：只在序列化时出现，等于实际条数
    payload = ir.model_dump(mode="json", by_alias=True)
    assert payload["score"]["measureCount"] == 2


def test_printed_numbers_win_over_accumulation() -> None:
    ir = assemble([read(1, printed=10), read(2), read(3)], skeleton())

    assert [measure.index for measure in ir.measures] == [1, 2, 3]
    assert [measure.printed for measure in ir.measures] == [10, 11, 12]


def test_unreadable_measure_becomes_rest() -> None:
    ir = assemble([read(1, unreadable=True)], skeleton())

    assert ir.measures[0].rest is True
    assert ir.measures[0].beats == []
