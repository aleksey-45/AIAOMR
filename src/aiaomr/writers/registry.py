"""按格式取 writer；未注册的格式启动即报错（E-06）。"""

from __future__ import annotations

from ..kernel.config import ConfigError
from .base import Writer
from .gp5.writer import GP5Writer


def get_writer(name: str) -> Writer:
    normalized = name.lower()
    if normalized in ("gp5", "guitarpro5"):
        return GP5Writer()
    raise ConfigError(f"未注册的输出格式：{name}")
