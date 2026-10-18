"""骨架读取的测试（规格 §2.2 S-01/S-05、§2.2.1 兜底；计划任务 8 的五个用例）。"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from aiaomr.kernel.config import load_config
from aiaomr.kernel.contracts import Crop
from aiaomr.providers.base import VisionResponse
from aiaomr.score.skeleton.read import (
    HeaderFacts,
    apply_header,
    apply_ts_inference,
    read_skeleton,
)


class FakeProvider:
    def __init__(self, content: dict) -> None:
        self.content = content
        self.calls = []

    def read(self, request):
        self.calls.append(request)
        return VisionResponse(
            content=json.dumps(self.content, ensure_ascii=False),
            usage={"prompt_tokens": 100, "completion_tokens": 20},
            duration_ms=3,
        )


def make_crop(tmp_path: Path, name: str = "header.png") -> Crop:
    path = tmp_path / name
    Image.new("RGB", (200, 80), "white").save(path)
    return Crop(path=str(path), box=[0, 0, 200, 80], kind="sheet", px=16000, deg=17.0, has_clef=True)


FULL = {
    "timeSignature": {"beats": 4, "beatType": 4},
    "keySignature": "BMajor",
    "tempo": 96,
    "tuning": [28, 33, 38, 43],
    "stringCount": 4,
    "title": "打上花火",
    "artist": "DAOKO",
}


def test_header_is_read(tmp_path: Path) -> None:
    cfg = load_config("deepseek_flash")
    skel = read_skeleton(make_crop(tmp_path), FakeProvider(FULL), cfg)

    assert skel.title == "打上花火"
    assert skel.artist == "DAOKO"
    assert skel.timeSignatures[0].beats == 4
    assert skel.keySignatures[0].key == "BMajor"
    assert skel.tempos[0].bpm == 96
    assert skel.tuning == [28, 33, 38, 43]
    assert skel.provenance.timeSignatures == "read"
    assert skel.provenance.tempos == "read"


def test_continuation_system_does_not_create_change_events(tmp_path: Path) -> None:
    cfg = load_config("deepseek_flash")
    skel = read_skeleton(make_crop(tmp_path), FakeProvider(FULL), cfg)
    before = (len(skel.timeSignatures), len(skel.keySignatures), len(skel.tempos))

    # 续行系统没印拍号/调号：模型返回 null，必须继承而不是产生变化事件
    facts = HeaderFacts(timeSignature=None, keySignature=None, tempo=None)
    apply_header(skel, facts, measure=17)

    assert (len(skel.timeSignatures), len(skel.keySignatures), len(skel.tempos)) == before


def test_changed_time_signature_is_recorded(tmp_path: Path) -> None:
    cfg = load_config("deepseek_flash")
    skel = read_skeleton(make_crop(tmp_path), FakeProvider(FULL), cfg)

    apply_header(skel, HeaderFacts(timeSignature={"beats": 2, "beatType": 4}), measure=29)

    assert skel.timeSignatures[-1].measure == 29
    assert skel.timeSignatures[-1].beats == 2


def test_title_falls_back_to_filename(tmp_path: Path) -> None:
    cfg = load_config("deepseek_flash")
    content = dict(FULL, title=None, artist=None, tempo=None)
    crop = make_crop(tmp_path, name="打上花火.png")

    skel = read_skeleton(crop, FakeProvider(content), cfg)

    assert skel.title == "打上花火"
    assert skel.provenance.title == "filename"


def test_tempo_defaults_to_120(tmp_path: Path) -> None:
    cfg = load_config("deepseek_flash")
    content = dict(FULL, tempo=None)

    skel = read_skeleton(make_crop(tmp_path), FakeProvider(content), cfg)

    assert skel.tempos[0].bpm == 120
    assert skel.provenance.tempos == "defaulted"


def test_ts_inference_from_bar_durations(tmp_path: Path) -> None:
    cfg = load_config("deepseek_flash")
    skel = read_skeleton(make_crop(tmp_path), FakeProvider(dict(FULL, timeSignature=None)), cfg)

    apply_ts_inference(skel, [3, 3, 3, 4], min_measures=cfg.skeleton.infer_ts_min_measures)

    assert skel.timeSignatures[0].beats == 3
    assert skel.provenance.timeSignatures == "inferred"


def test_key_signature_is_normalized(tmp_path: Path) -> None:
    """模型常写 "Bb major"，要规范成 Guitar Pro 的 "BbMajor"。"""
    cfg = load_config("deepseek_flash")
    content = dict(FULL, keySignature="Bb major")

    skel = read_skeleton(make_crop(tmp_path), FakeProvider(content), cfg)

    assert skel.keySignatures[0].key == "BbMajor"
