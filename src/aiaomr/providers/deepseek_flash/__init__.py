"""DeepSeek V4.1-Flash 接入：能力声明 + 调用实现（规格 §2.3、§4.1）。"""

from .caps import CAPS
from .client import DeepSeekClient, StubClient

__all__ = ["CAPS", "DeepSeekClient", "StubClient"]
