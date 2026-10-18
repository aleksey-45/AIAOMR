"""调号识别：把"谱号 + 调号 + 拍号"那一小区裁出来，只问一件事（规格 §2.2 P1）。

调号是骨架参数，必须在读小节之前定死。整页给模型看时它数不准升降号（打上花火
五个升号读成 E 大调），所以这里改成窄任务：小图、只问调号、要求报升降号个数。
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from ...kernel.config import Config
from ...kernel.contracts import Crop
from ...providers.base import ImageInput, ProviderError, VisionRequest
from .read import normalize_key

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "keysig.md"


class KeyFacts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    keySignature: str | None = None
    accidentals: dict | None = None
    reason: str | None = None


def load_prompt(version: str = "p0") -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").replace("{{promptVersion}}", version)


def parse_key(raw: str) -> str | None:
    """严格解析；返回 Guitar Pro 名字（`BMajor`），没读到返回 None。"""
    if not raw or not raw.strip():
        return None
    try:
        facts = KeyFacts.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError):
        return None
    if not facts.keySignature:
        return None
    return normalize_key(facts.keySignature)


def read_key_signature(
    key_crop: Crop,
    provider,
    cfg: Config,
    emit=None,
    call_id: str = "keysig",
) -> str | None:
    """窄问题：这张小图的调号是什么。失败就返回 None，交给骨架自己的读数兜底。"""
    path = Path(key_crop.path)
    if not path.exists():
        return None
    if emit is not None:
        emit("skeleton", "keysig.started", callId=call_id)
    request = VisionRequest(
        call_id=call_id,
        prompt_prefix=load_prompt(),
        prompt_suffix="这是第一个系统开头的谱号、调号、拍号区。",
        images=(ImageInput(path.read_bytes(), "image/png"),),
        max_tokens=600,
        thinking=False,
    )
    try:
        response = provider.read(request)
        key = parse_key(response.content)
    except ProviderError:
        key = None
    if emit is not None:
        emit("skeleton", "keysig.done", key=key)
    return key
