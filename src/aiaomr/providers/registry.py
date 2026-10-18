"""按名字取 provider；没注册的名字启动即报错（§2.3.2 checklist 第 2 条）。"""

from __future__ import annotations

from pathlib import Path

from ..kernel.config import Config
from ..kernel.config import ConfigError
from .base import VisionProvider
from .deepseek_flash import CAPS, DeepSeekClient, StubClient


def get_provider(
    name: str,
    cfg: Config,
    api_key: str | None = None,
    offline_dir: str | Path | None = None,
) -> VisionProvider:
    """`name` 必须与 `configs/providers/<name>.toml` 对应；未知名字直接报错。"""
    normalized = name.replace("-", "_")
    if normalized == "deepseek_flash":
        if offline_dir is not None:
            return StubClient(CAPS, offline_dir)
        return DeepSeekClient(CAPS, api_key=api_key)
    raise ConfigError(f"未注册的 provider：{name}")
