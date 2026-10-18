"""输出格式层（L4）的公共接口（规格 §2.8 E-01..E-07）。

writer 只吃 IR，不许读 `out/` 里的中间产物（E-07）。写出必须经过
`validate → build → verify` 三步，任一步失败都不产出文件。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..kernel.errors import ErrorCode
from ..kernel.ir import IR


class WriterError(RuntimeError):
    """写出失败；带内核错误码（E_BUILD_VALIDATE / E_BUILD_ROUNDTRIP）。"""

    def __init__(self, code: ErrorCode, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or []


@dataclass
class Report:
    """一次写出的结果：文件、字节数、小节数、往返核对结论。"""

    path: str
    bytes: int
    measures: int
    roundtrip: str
    warnings: list[str] = field(default_factory=list)


class Writer(Protocol):
    name: str

    def write(self, ir: IR, path: str) -> Report: ...
