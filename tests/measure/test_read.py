"""读谱小节层的测试（规格 §2.4 RD-06b、RD-07、RD-04；计划任务 7 的五个用例）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from aiaomr.kernel.config import load_config
from aiaomr.kernel.contracts import Crop, MeasureBox, MeasureTask
from aiaomr.kernel.errors import ErrorCode
from aiaomr.measure.read import build_suffix, max_tokens_for, read_systems
from aiaomr.providers.base import VisionResponse

VALID = {
    "measures": [
        {
            "index": 1,
            "beats": [
                {
                    "duration": "quarter",
                    "dots": 0,
                    "rest": False,
                    "notes": [
                        {"string": 1, "fret": 2, "pitch": 45, "digit": "2", "tieFromPrevious": False}
                    ],
                }
            ],
        },
        {
            "index": 2,
            "beats": [
                {
                    "duration": "eighth",
                    "dots": 0,
                    "rest": False,
                    "notes": [{"string": 4, "fret": 5, "pitch": 33, "digit": "5"}],
                }
            ],
        },
    ]
}


class FakeProvider:
    def __init__(self, contents: list[dict], max_concurrency: int = 4) -> None:
        self.contents = list(contents)
        self.calls = []
        self.caps = type("Caps", (), {"max_concurrency": max_concurrency})()

    def read(self, request):
        self.calls.append(request)
        index = min(len(self.calls) - 1, len(self.contents) - 1)
        return VisionResponse(
            content=json.dumps(self.contents[index], ensure_ascii=False),
            usage={"prompt_tokens": 100, "completion_tokens": 10, "prompt_cache_miss_tokens": 100},
            duration_ms=5,
        )


def make_task(tmp_path: Path, has_clef: bool = True, measures: tuple[int, ...] = (1, 2)) -> MeasureTask:
    Image.new("RGB", (80, 40), "white").save(tmp_path / "crop.png")
    boxes = [
        MeasureBox(index=index, printed=None, x0=10.0 * index, x1=10.0 * (index + 1), width=10.0)
        for index in measures
    ]
    return MeasureTask(
        system=1,
        measures=boxes,
        crop=Crop(
            path=str(tmp_path / "crop.png"),
            box=[0.0, 0.0, 80.0, 40.0],
            kind="system",
            px=3200,
            deg=17.0,
            has_clef=has_clef,
        ),
        hints={"stringCount": 4, "tuning": [28, 33, 38, 43], "page": 1, "measures": list(measures)},
        callId="01s01p01",
    )


def test_valid_response_is_converted_with_string_flip(tmp_path: Path) -> None:
    cfg = load_config("deepseek_flash")
    provider = FakeProvider([VALID])

    results = read_systems([make_task(tmp_path)], provider, cfg)

    assert len(results) == 1
    result = results[0]
    assert result.errorCode is None
    first = result.reads[0].beats[0].notes[0]
    # 模型按 Guitar Pro 习惯（最上面一条线 = 1）输出，IR 要翻成 1 = 最低弦
    assert first.string == 4
    assert first.pitch == 43 + 2
    assert first.digit is not None and first.digit.value == "2" and first.digit.glyphs == 1
    second = result.reads[1].beats[0].notes[0]
    assert second.string == 1 and second.pitch == 28 + 5


def test_missing_pitch_is_optional_not_an_error(tmp_path: Path) -> None:
    """pitch 是可选的对账项：模型不给也能用调弦 + 品数算出权威音高（F-01）。"""
    content = {"measures": [{"index": 1, "beats": [
        {"duration": "quarter", "notes": [{"string": 2, "fret": 3}]}]}]}
    cfg = load_config("deepseek_flash")
    provider = FakeProvider([content])

    results = read_systems([make_task(tmp_path, measures=(1,))], provider, cfg)

    assert results[0].errorCode is None
    note = results[0].reads[0].beats[0].notes[0]
    assert note.pitchClaim is None
    assert note.string == 3  # GP string 2 → IR string 3
    assert note.pitch == 38 + 3


def test_measure_index_mismatch_is_schema_error(tmp_path: Path) -> None:
    swapped = {"measures": list(reversed(VALID["measures"])),}
    cfg = load_config("deepseek_flash")
    provider = FakeProvider([swapped])

    results = read_systems([make_task(tmp_path)], provider, cfg)

    assert results[0].errorCode is ErrorCode.E_VLM_SCHEMA
    assert any("小节号不匹配" in (call.prompt_suffix or "") for call in provider.calls[1:])


def test_crop_without_clef_is_refused_before_calling_model(tmp_path: Path) -> None:
    cfg = load_config("deepseek_flash")
    provider = FakeProvider([VALID])

    with pytest.raises(ValueError):
        read_systems([make_task(tmp_path, has_clef=False)], provider, cfg)
    assert provider.calls == []


def test_two_character_digit_is_one_digit_with_two_glyphs(tmp_path: Path) -> None:
    content = json.loads(json.dumps(VALID))
    content["measures"] = content["measures"][:1]
    content["measures"][0]["beats"][0]["notes"][0]["digit"] = "12"
    cfg = load_config("deepseek_flash")
    provider = FakeProvider([content])

    results = read_systems([make_task(tmp_path, measures=(1,))], provider, cfg)
    note = results[0].reads[0].beats[0].notes[0]

    assert note.digit.value == "12"
    assert note.digit.glyphs == 2
    assert len(results[0].reads[0].beats[0].notes) == 1


def test_max_tokens_follows_rule() -> None:
    assert max_tokens_for("400*measures+800", 8) == 4000
    assert max_tokens_for("400*measures+800", 0) == 1200


def test_suffix_injects_clef_key_and_string_names(tmp_path: Path) -> None:
    """提示词必须给全：谱号在稳定前缀里，调号和每根弦的音名在后缀里。"""
    cfg = load_config("deepseek_flash")
    task = make_task(tmp_path, measures=(1,))
    task.hints.update({"keySignature": "BMajor", "clef": "bass", "timeSignature": "6/8"})

    suffix = build_suffix(task, cfg)

    assert "第 1 小节" in suffix
    assert "拍号：6/8" in suffix
    assert "调号：B 大调" in suffix
    assert "第 1 弦 G2(43)" in suffix
    assert "第 4 弦 E1(28)" in suffix
    assert "TAB 顶线 = string 1，底线 = string 4" in suffix
