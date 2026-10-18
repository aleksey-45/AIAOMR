"""kernel 共享数据结构的测试。

依据：规格 §3.2（中间结构）、§3.3（错误码）、§2.0 LAY 规则。
contracts.py 与 errors.py 只放数据：不许有 IO，不许有业务判断。
"""

import pytest
from pydantic import ValidationError

from aiaomr.kernel.contracts import (
    Abstain,
    Crop,
    Judgement,
    MeasureBox,
    MeasureRead,
    MeasureResult,
    MeasureRhythm,
    MeasureTask,
    Page,
    PageSet,
    RhythmBeat,
    Skeleton,
    StaffLine,
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


def test_system_carries_staff_band_tab_band_and_boxes():
    system = System(
        id=1,
        page=1,
        y0=100.0,
        y1=160.0,
        tabY0=180.0,
        tabY1=240.0,
        tabLines=[180.0, 195.0, 210.0, 225.0],
        measures=[measure_box(1), measure_box(2)],
        headerX0=40.0,
        headerX1=90.0,
    )
    assert len(system.measures) == 2
    assert len(system.tabLines) == 4


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


# ---- 读五线谱层的数据结构（docs/spec-staff.md §10、spec-v3.md §3.2） ----


def staff_line_payload(**overrides):
    data = {"top": 100, "bottom": 102, "center": 101.0}
    data.update(overrides)
    return data


def rhythm_beat_payload(**overrides):
    data = {
        "x": 120.5,
        "kind": "note",
        "duration": "eighth",
        "dots": 1,
        "noteCount": 1,
        "head": "filled",
        "beams": 2,
        "group": 4,
        "confidence": 0.9,
        "evidence": {"stem": "up"},
    }
    data.update(overrides)
    return data


def test_staff_line_is_one_run_of_a_staff_line():
    """R-10：谱线行交出起止行号与中心（厚度由 bottom-top+1 得到）。"""
    line = StaffLine(top=100, bottom=102, center=101.0)
    assert line.top == 100
    assert line.bottom == 102
    assert line.center == 101.0
    assert line.model_dump() == {"top": 100, "bottom": 102, "center": 101.0}


@pytest.mark.parametrize("field", ["top", "bottom", "center"])
def test_staff_line_requires_every_field(field):
    payload = staff_line_payload()
    del payload[field]
    with pytest.raises(ValidationError):
        StaffLine.model_validate(payload)


def test_staff_line_forbids_extra_fields():
    with pytest.raises(ValidationError):
        StaffLine.model_validate(staff_line_payload(thickness=3))


def test_system_staff_lines_default_to_empty_and_accept_runs():
    """老构图没有谱线行信息，staffLines 必须能缺省；`staff/` 只读不重新定位（§12.2）。"""
    without = System(
        id=1,
        page=1,
        y0=100.0,
        y1=160.0,
        tabY0=180.0,
        tabY1=240.0,
        tabLines=[180.0, 195.0],
        measures=[measure_box(1)],
        headerX0=40.0,
        headerX1=90.0,
    )
    assert without.staffLines == []

    with_runs = System.model_validate(
        {
            "id": 1,
            "page": 1,
            "y0": 100.0,
            "y1": 160.0,
            "tabY0": 180.0,
            "tabY1": 240.0,
            "tabLines": [180.0, 195.0],
            "measures": [],
            "headerX0": 40.0,
            "headerX1": 90.0,
            "staffLines": [
                {"top": 100, "bottom": 102, "center": 101.0},
                {"top": 112, "bottom": 114, "center": 113.0},
            ],
        }
    )
    assert [line.center for line in with_runs.staffLines] == [101.0, 113.0]
    assert all(isinstance(line, StaffLine) for line in with_runs.staffLines)


def test_rhythm_beat_matches_the_spec_fields():
    """§10：一拍上的事实，字段名与默认值照规格写死。"""
    beat = RhythmBeat.model_validate(rhythm_beat_payload())
    assert set(beat.model_dump()) == {
        "x",
        "kind",
        "duration",
        "dots",
        "noteCount",
        "head",
        "beams",
        "group",
        "confidence",
        "evidence",
    }
    assert beat.duration == "eighth"
    assert beat.dots == 1
    assert beat.head == "filled"
    assert beat.group == 4

    default = RhythmBeat(x=10.0, kind="rest")
    assert default.duration is None
    assert default.dots == 0
    assert default.noteCount == 1
    assert default.head is None
    assert default.beams == 0
    assert default.group is None
    assert default.confidence == 0.0
    assert default.evidence == {}


@pytest.mark.parametrize(
    "field,bad",
    [
        ("kind", "bogus"),
        ("kind", "notehead"),
        ("duration", "64th"),
        ("duration", "quarter."),
        ("head", "open"),
        ("head", "solid"),
    ],
)
def test_rhythm_beat_literals_reject_unknown_values(field, bad):
    with pytest.raises(ValidationError):
        RhythmBeat.model_validate(rhythm_beat_payload(**{field: bad}))


def test_rhythm_beat_accepts_every_spec_duration():
    for duration in ("whole", "half", "quarter", "eighth", "16th", "32nd"):
        assert RhythmBeat(x=1.0, kind="note", duration=duration).duration == duration
    # duration 可以为空：读不出时是 abstain，不是猜一个值（§10）。
    assert RhythmBeat(x=1.0, kind="note", duration=None).duration is None


def test_rhythm_beat_dots_are_zero_to_two():
    """附点最多两个（§10 字段注释 `dots: int = 0`，spec-staff §5.5 只读单/双附点）。"""
    for dots in (0, 1, 2):
        assert RhythmBeat(x=1.0, kind="note", dots=dots).dots == dots
    for dots in (-1, 3):
        with pytest.raises(ValidationError):
            RhythmBeat(x=1.0, kind="note", dots=dots)


def test_rhythm_beat_confidence_is_a_zero_to_one_ratio():
    """§10：confidence 是 0..1 的综合置信度，不是任意数。"""
    assert RhythmBeat(x=1.0, kind="note", confidence=0.0).confidence == 0.0
    assert RhythmBeat(x=1.0, kind="note", confidence=1.0).confidence == 1.0
    for bad in (-0.1, 1.1):
        with pytest.raises(ValidationError):
            RhythmBeat(x=1.0, kind="note", confidence=bad)


def test_rhythm_beat_forbids_extra_fields():
    with pytest.raises(ValidationError):
        RhythmBeat.model_validate(rhythm_beat_payload(stem="up"))


def test_rhythm_beat_evidence_is_per_instance():
    """默认容器不能共享：这一拍的证据不许漏到下一拍。"""
    beat_a = RhythmBeat(x=1.0, kind="note")
    beat_b = RhythmBeat(x=2.0, kind="note")
    beat_a.evidence["stem"] = "up"
    assert beat_b.evidence == {}


def test_abstain_carries_ar_reason_code():
    """§10：读不准时记 AR-xx 编号与位置，不许往下编。"""
    abstain = Abstain(reason="AR-03", measure=12)
    assert abstain.reason == "AR-03"
    assert abstain.measure == 12
    assert abstain.beat is None
    assert abstain.detail == {}

    detailed = Abstain(reason="AR-12", measure=5, beat=2, detail={"noteCount": 3})
    assert detailed.beat == 2
    assert detailed.detail["noteCount"] == 3


@pytest.mark.parametrize(
    "bad_reason",
    ["AR-3", "AR-003", "ar-03", "AR-0a", "E_VLM_EMPTY", "", "AR-"],
)
def test_abstain_reason_must_be_ar_two_digits(bad_reason):
    with pytest.raises(ValidationError):
        Abstain(reason=bad_reason, measure=1)


def test_abstain_requires_measure_and_forbids_extra_fields():
    with pytest.raises(ValidationError):
        Abstain(reason="AR-01")
    with pytest.raises(ValidationError):
        Abstain(reason="AR-01", measure=1, symbol="x")


def test_measure_rhythm_organizes_beats_and_abstains():
    """§10：一个谱面小节的读谱结果，status 只有三种。"""
    rhythm = MeasureRhythm(
        index=3,
        status="ok",
        beats=[RhythmBeat(x=10.0, kind="note", duration="quarter")],
        abstains=[Abstain(reason="AR-05", measure=3, beat=2)],
        ticks=3840,
        deg=12.0,
    )
    assert rhythm.index == 3
    assert rhythm.status == "ok"
    assert len(rhythm.beats) == 1
    assert rhythm.abstains[0].reason == "AR-05"
    assert rhythm.ticks == 3840
    assert rhythm.deg == 12.0

    default = MeasureRhythm(index=1, status="unknown")
    assert default.beats == []
    assert default.abstains == []
    assert default.ticks == 0
    assert default.deg == 0.0


def test_measure_rhythm_status_is_one_of_three():
    for status in ("ok", "partial", "unknown"):
        assert MeasureRhythm(index=1, status=status).status == status
    for bad in ("bogus", "failed", "OK"):
        with pytest.raises(ValidationError):
            MeasureRhythm(index=1, status=bad)


def test_measure_rhythm_forbids_extra_fields_and_shares_no_default_lists():
    with pytest.raises(ValidationError):
        MeasureRhythm(index=1, status="ok", duration=3840)

    first = MeasureRhythm(index=1, status="partial")
    second = MeasureRhythm(index=2, status="partial")
    first.beats.append(RhythmBeat(x=1.0, kind="note"))
    first.abstains.append(Abstain(reason="AR-01", measure=1))
    assert second.beats == []
    assert second.abstains == []
