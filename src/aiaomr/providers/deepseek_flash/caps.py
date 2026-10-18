"""DeepSeek V4.1-Flash 的能力声明（规格 §2.3.2）。

价格是人民币 / 百万 token，谷价；峰价是谷价的两倍（§2.3.2、§4.1）。
"""

from __future__ import annotations

from ..base import ProviderCapabilities

CAPS = ProviderCapabilities(
    name="deepseek_flash",
    model="deepseek-flash",
    supports_vision=True,
    image_token_rule="1024 * clamp(P, 0.296MP, 1.69MP) / 1.69MP, floor 180",
    max_side_px=8192,
    max_images_per_request=14,
    max_image_bytes=32 * 1024 * 1024,
    supported_formats=("image/png", "image/jpeg", "image/webp", "image/gif"),
    supports_json_mode=True,
    supports_detail_param=True,
    supports_thinking_toggle=True,
    max_concurrency=2500,
    pricing={"miss": 1.0, "hit": 0.02, "out": 4.0},
    peak_pricing={"miss": 2.0, "hit": 0.04, "out": 8.0},
    peak_hours="北京时间周一至周五 09:00–12:00、14:00–18:00（中国法定节假日除外）",
    retry_empty=2,
    retry_http=5,
)
