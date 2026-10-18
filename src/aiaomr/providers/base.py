"""模型接入层（L1）的公共接口与能力声明（规格 §2.3、§2.3.2）。

这一层是**唯一允许发 HTTP 的地方**；其余层只依赖这里的 `VisionProvider` 协议和
`ProviderCapabilities`。业务代码里不许出现模型名、endpoint、`detail` 取值这类厂商字面量。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..kernel.errors import ErrorCode


@dataclass(frozen=True)
class ProviderCapabilities:
    """能力声明：新增 provider 时必须填满，缺项启动即失败（§2.3.2）。"""

    name: str
    model: str
    supports_vision: bool
    image_token_rule: str
    max_side_px: int
    max_images_per_request: int
    max_image_bytes: int
    supported_formats: tuple[str, ...]
    supports_json_mode: bool
    supports_detail_param: bool
    supports_thinking_toggle: bool
    max_concurrency: int
    # 人民币 / 百万 token；`pricing` 是谷价，`peak_pricing` 是峰价。
    pricing: dict[str, float]
    peak_pricing: dict[str, float]
    peak_hours: str
    retry_empty: int
    retry_http: int


@dataclass(frozen=True)
class ImageInput:
    """一张要送出去的图（字节 + MIME 类型）。"""

    data: bytes
    media_type: str


@dataclass(frozen=True)
class VisionRequest:
    """一次视觉调用。`prompt_prefix` 必须逐字节稳定（为了命中缓存），变量放 `prompt_suffix`。"""

    call_id: str
    prompt_prefix: str
    prompt_suffix: str
    images: tuple[ImageInput, ...] = field(default_factory=tuple)
    max_tokens: int = 4000
    thinking: bool = False


@dataclass(frozen=True)
class VisionResponse:
    """一次调用的结果：模型文本、原始用量、耗时、重试次数。"""

    content: str
    usage: dict
    duration_ms: int
    retry_count: int = 0
    raw: dict | None = None


class ProviderError(RuntimeError):
    """带错误码的 provider 失败；错误码来自内核，不许自创字符串。"""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class VisionProvider(Protocol):
    """接入实现只需要这一个方法：给一次请求，回一段模型输出。"""

    caps: ProviderCapabilities

    def read(self, request: VisionRequest) -> VisionResponse: ...
