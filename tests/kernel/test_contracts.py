"""kernel 共享数据结构的测试。

依据：规格 §3.2（中间结构）、§3.3（错误码）、§2.0 LAY 规则。
contracts.py 与 errors.py 只放数据：不许有 IO，不许有业务判断。
"""

import pytest
from pydantic import ValidationError

from aiaomr.kernel.contracts import (
    Crop,
    Judgement,
    MeasureBox,
    MeasureRead,
    MeasureResult,
    MeasureTask,
    Page,
    PageSet,
    Skeleton,
    System,
)
from aiaomr.kernel.errors import (
    ERROR_EXIT_CODE,
    ERROR_SEVERITY,
    ErrorCode,
    ErrorSeverity,
)
from aiaomr.kernel.ir import SkeletonProvenance

SPEC_ERROR_CODES = {
    "E_INPUT_UNREADABLE",
    "E_NO_SYSTEM",
    "E_TAB_STAFF_MISSING",
    "E_SKELETON_UNREAD",
    "E_VLM_HTTP",
    "E_VLM_EMPTY",
    "E_VLM_SCHEMA",
    "E_BUDGET_EXCEEDED",
    "E_BUILD_VALIDATE",
    "E_BUILD_ROUNDTRIP",
    "E_AUDIT",
}


def crop_payload(**overrides):
    data = {
        "path": "out/song/crops/c0001.png",
        "box": [0, 0, 100, 100],
        "kind": "system",
        "px": 1_000_000,
        "deg": 12.0,
        "has_clef": True,
    }
    data.update(overrides)
    return data


def measure_box(index=1):
    return MeasureBox(index=index, printed=index, x0=0, x1=100, width=100)


def test_crop_requires_has_clef():
    payload = crop_payload()
    del payload["has_clef"]
    with pytest.raises(ValidationError):
        Crop.model_validate(payload)


def test_crop_has_clef_is_a_strict_bool():
    crop = Crop.model_validate(crop_payload(has_clef=False))
    assert crop.has_clef is False
    assert crop.model_dump()["has_clef"] is False
    # 真值字符串不能绕过 RD-04 的谱号区检查。
    with pytest.raises(ValidationError):
        Crop.model_validate(crop_payload(has_clef="yes"))


def test_crop_box_has_exactly_four_edges():
    with pytest.raises(ValidationError):
        Crop.model_validate(crop_payload(box=[0, 0, 100]))


def test_crop_kind_is_one_of_the_three_spec_kinds():
    assert Crop.model_validate(crop_payload(kind="reread")).kind == "reread"
    with pytest.raises(ValidationError):
        Crop.model_validate(crop_payload(kind="bogus"))


def test_page_set_class_uses_the_spec_json_key():
    page_set = PageSet(pages=[], class_=3, degGlobal=12.5)
    assert page_set.class_ == 3
    assert page_set.model_dump(by_alias=True)["class"] == 3
    from_json = PageSet.model_validate(
        {"pages": [], "class": 3, "degGlobal": 12.5}
    )
    assert from_json.class_ == 3
def test_page_owns_its_systems():
    page = Page(path="pages/p1.png", width=2000, height=3000, deg=12.0, systems=[])
    assert page.systems == []


def test_measure_task_carries_one_crop_and_its_measure_boxes():
    task = MeasureTask(
        system=1,
        measures=[measure_box(1), measure_box(2)],
        crop=Crop.model_validate(crop_payload()),
        hints={"stringCount": 4},
        callId="c0001",
    )
    assert task.crop.has_clef is True
    assert task.callId == "c0001"
    assert task.hints["stringCount"] == 4


def test_measure_read_is_one_measure_of_facts():
    read = MeasureRead(index=7, beats=[], unreadable=True)
    assert read.index == 7
    assert read.unreadable is True


def test_measure_result_groups_reads_of_one_call():
    result = MeasureResult(
        callId="c0001",
        reads=[MeasureRead(index=1, beats=[], unreadable=False)],
    )
    assert result.callId == "c0001"
    assert len(result.reads) == 1
    assert result.errorCode is None


def test_skeleton_keeps_tiered_provenance():
    skeleton = Skeleton(
        timeSignatures=[{"measure": 1, "beats": 4, "beatType": 4}],
        keySignatures=[],
        tempos=[{"measure": 1, "bpm": 120}],
        tuning=[28, 33, 38, 43],
        stringCount=4,
        title="打上花火",
        artist="",
        provenance=SkeletonProvenance(
            timeSignatures="inferred",
            tuning="read",
            keySignatures="defaulted",
            tempos="defaulted",
            title="filename",
            artist="empty",
        ),
    )
    assert skeleton.provenance.timeSignatures == "inferred"
    assert skeleton.stringCount == 4


def test_judgement_is_the_ir_judgement():
    from aiaomr.kernel import ir

    assert Judgement is ir.Judgement
    judgement = Judgement(
        id="j001",
        measure=12,
        rule="bar_duration",
        claimed=4320,
        expected=3840,
        final=3840,
        reason="时值之和对不上拍号",
        model="stub-vision",
        promptVersion="p0",
        crops=["out/song/crops/c0001.png"],
        ts="2026-10-18T00:00:00.000Z",
    )
    assert judgement.final == 3840


def test_error_codes_match_the_spec_table():
    assert {code.value for code in ErrorCode} == SPEC_ERROR_CODES


def test_error_severity_mapping_covers_every_code():
    assert set(ERROR_SEVERITY) == set(ErrorCode)
    assert ERROR_SEVERITY[ErrorCode.E_TAB_STAFF_MISSING] is ErrorSeverity.SYSTEM
    assert ERROR_SEVERITY[ErrorCode.E_VLM_EMPTY] is ErrorSeverity.SYSTEM
    assert ERROR_SEVERITY[ErrorCode.E_VLM_SCHEMA] is ErrorSeverity.SYSTEM
    assert ERROR_SEVERITY[ErrorCode.E_VLM_HTTP] is ErrorSeverity.GLOBAL
    assert ERROR_SEVERITY[ErrorCode.E_BUDGET_EXCEEDED] is ErrorSeverity.GLOBAL
    assert ERROR_SEVERITY[ErrorCode.E_NO_SYSTEM] is ErrorSeverity.STAGE


def test_only_stage_and_global_codes_carry_an_exit_code():
    assert ERROR_EXIT_CODE[ErrorCode.E_INPUT_UNREADABLE] == 1
    assert ERROR_EXIT_CODE[ErrorCode.E_NO_SYSTEM] == 1
    assert ERROR_EXIT_CODE[ErrorCode.E_SKELETON_UNREAD] == 1
    assert ERROR_EXIT_CODE[ErrorCode.E_VLM_HTTP] == 2
    assert ERROR_EXIT_CODE[ErrorCode.E_BUILD_VALIDATE] == 2
    assert ERROR_EXIT_CODE[ErrorCode.E_BUILD_ROUNDTRIP] == 2
    assert ERROR_EXIT_CODE[ErrorCode.E_AUDIT] == 2
    assert ERROR_EXIT_CODE[ErrorCode.E_BUDGET_EXCEEDED] == 3
    for system_level in (
        ErrorCode.E_TAB_STAFF_MISSING,
        ErrorCode.E_VLM_EMPTY,
        ErrorCode.E_VLM_SCHEMA,
    ):
        assert system_level not in ERROR_EXIT_CODE
