"""调号窄问题的测试（规格 §2.2 P1）。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from aiaomr.kernel.config import load_config
from aiaomr.kernel.contracts import Crop
from aiaomr.providers.base import VisionResponse
from aiaomr.score.skeleton.keysig import parse_key, read_key_signature


class FakeProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = []

    def read(self, request):
        self.calls.append(request)
        return VisionResponse(content=self.content, usage={}, duration_ms=1)


def make_crop(tmp_path: Path) -> Crop:
    path = tmp_path / "keysig.png"
    Image.new("RGB", (240, 80), "white").save(path)
    return Crop(path=str(path), box=[0, 0, 240, 80], kind="sheet", px=19200, deg=17.0, has_clef=True)


def test_parse_key_normalizes_names() -> None:
    assert parse_key('{"keySignature": "B major"}') == "BMajor"
    assert parse_key('{"keySignature": "Bb major"}') == "BbMajor"
    assert parse_key('{"keySignature": "F# minor"}') == "F#Minor"


def test_parse_key_returns_none_when_unreadable() -> None:
    assert parse_key('{"keySignature": null, "reason": "blurry"}') is None
    assert parse_key("not json") is None
    assert parse_key("") is None


def test_read_key_signature_uses_provider(tmp_path: Path) -> None:
    cfg = load_config("deepseek_flash")
    provider = FakeProvider('{"keySignature": "BMajor", "accidentals": {"kind": "sharp", "count": 5}}')

    key = read_key_signature(make_crop(tmp_path), provider, cfg)

    assert key == "BMajor"
    assert len(provider.calls) == 1
    assert "调号" in provider.calls[0].prompt_prefix
