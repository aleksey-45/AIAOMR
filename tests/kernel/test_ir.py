"""IR v3.0 的测试。

依据：规格 §3.1（IR 结构与不变量）、§1.5（ir.py 是唯一 schema 来源）。
"""

import json

import pytest
from pydantic import ValidationError

from aiaomr.kernel.ir import IR


def ir_payload(measure_count=2, **score_overrides):
    """造一份最小的合法 IR 负载；局部改动用来验证不变量。"""
    score = {
        "title": "打上花火",
        "artist": "DAOKO",
        "tabber": "",
        "tuning": [28, 33, 38, 43],
        "stringCount": 4,
        "timeSignatures": [{"measure": 1, "beats": 4, "beatType": 4}],
        "keySignatures": [{"measure": 1, "key": "BMajor"}],
        "tempos": [{"measure": 1, "bpm": 96}],
        "clefTranspose": -12,
        "fretCount": 24,
    }
    score.update(score_overrides)
    beat = {
        "duration": "quarter",
        "dots": 0,
        "rest": True,
        "notes": [],
        "prov": "read",
        "evidence": {"system": 1, "crop": [0, 0, 100, 100], "call": "c0001"},
    }
    measures = [
        {"index": i, "printed": i, "rest": True, "multiRest": 1, "beats": [beat]}
        for i in range(1, measure_count + 1)
    ]
    return {
        "version": "3.0",
        "meta": {
            "provider": "stub",
            "model": "stub-vision",
            "promptVersion": "p0",
            "schemaVersion": "3.0",
            "generatedAt": "2026-10-18T00:00:00.000Z",
        },
        "source": {
            "class": 3,
            "kind": "image",
            "files": ["pages/p1.png"],
            "inputSha256": "0" * 64,
        },
        "score": score,
        "skeletonProvenance": {
            "timeSignatures": "read",
            "tuning": "read",
            "keySignatures": "read",
            "tempos": "read",
            "title": "read",
            "artist": "read",
        },
        "measures": measures,
    }


def test_ir_roundtrip_and_invariants(tmp_path):
    # 第一段：存成 JSON 再读回来，两者相等。
    ir = IR.model_validate(ir_payload())
    path = tmp_path / "ir.json"
    ir.to_json(path)
    assert IR.from_json(path) == ir

    # 第二段：调弦不严格递增，必须抛校验错误。
    payload = ir_payload()
    payload["score"]["tuning"] = [28, 33, 33, 43]
    with pytest.raises(ValidationError):
        IR.model_validate(payload)

    # 第三段：小节总数和实际条数不一致，必须抛校验错误。
    payload = ir_payload()
    payload["score"]["measureCount"] = 3
    with pytest.raises(ValidationError):
        IR.model_validate(payload)


def test_ir_serializes_measure_count_as_computed_field(tmp_path):
    ir = IR.model_validate(ir_payload(measure_count=4))
    path = tmp_path / "ir.json"
    ir.to_json(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["score"]["measureCount"] == 4
    assert raw["score"]["measureCount"] == len(raw["measures"])


def test_ir_accepts_matching_measure_count():
    payload = ir_payload(measure_count=2)
    payload["score"]["measureCount"] = 2
    ir = IR.model_validate(payload)
    assert len(ir.measures) == 2


def test_ir_accepts_json_without_measure_count(tmp_path):
    payload = ir_payload()
    path = tmp_path / "ir.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    ir = IR.from_json(path)
    assert len(ir.measures) == 2


def test_ir_requires_tuning_length_to_equal_string_count():
    payload = ir_payload()
    payload["score"]["tuning"] = [28, 33, 38]
    with pytest.raises(ValidationError):
        IR.model_validate(payload)


@pytest.mark.parametrize(
    "field_name, entry",
    [
        ("timeSignatures", {"measure": 2, "beats": 4, "beatType": 4}),
        ("keySignatures", {"measure": 2, "key": "EMajor"}),
        ("tempos", {"measure": 2, "bpm": 120}),
    ],
)
def test_ir_requires_strictly_increasing_measure_numbers(field_name, entry):
    payload = ir_payload()
    # 两条同一小节、以及倒序，都算不严格递增。
    payload["score"][field_name] = [dict(entry), dict(entry)]
    with pytest.raises(ValidationError):
        IR.model_validate(payload)

    payload = ir_payload()
    first = dict(entry)
    second = dict(entry)
    first["measure"] = 3
    second["measure"] = 2
    payload["score"][field_name] = [first, second]
    with pytest.raises(ValidationError):
        IR.model_validate(payload)


def test_ir_to_json_keeps_chinese_unescaped(tmp_path):
    ir = IR.model_validate(ir_payload())
    path = tmp_path / "ir.json"
    ir.to_json(path)
    text = path.read_text(encoding="utf-8")
    assert "打上花火" in text
    assert "\\u6253" not in text


def test_ir_to_json_is_atomic(tmp_path, monkeypatch):
    ir = IR.model_validate(ir_payload())
    path = tmp_path / "ir.json"
    ir.to_json(path)
    good = path.read_text(encoding="utf-8")
    assert not (tmp_path / "ir.json.tmp").exists()

    def interrupted(src, dst):
        raise RuntimeError("写到一半被杀")

    monkeypatch.setattr("os.replace", interrupted)
    with pytest.raises(RuntimeError):
        ir.to_json(path)
    # 目标文件必须还是上一份完整内容，不能出现半个文件。
    assert path.read_text(encoding="utf-8") == good


def test_ir_schema_is_generated_from_the_model():
    schema = IR.model_json_schema()
    assert schema["title"] == "IR"
    assert "measures" in schema["properties"]
    assert json.dumps(schema)
