"""判据的公共底座：`Finding` 与 `Criterion`。

依据：`docs/spec-staff.md` §5。判据只回答"有没有、几个、在哪"，并给出 bbox 与证据；
判据之间只通过 `findings` 传递结论，不共享中间状态。阈值一律以 deg 为单位（R-03）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .context import GeoContext


@dataclass
class Finding:
    """一条几何判据的结论。`value` 的含义由 `kind` 决定。"""

    kind: str
    value: float
    bbox: tuple[float, float, float, float]
    evidence: dict = field(default_factory=dict)


class Criterion:
    """判据的公共接口；新增判据只要实现 `detect`，并在文件名上体现出是哪一类。"""

    name = "criterion"

    def detect(
        self,
        ctx: GeoContext,
        findings: dict[str, list[Finding]] | None = None,
    ) -> list[Finding]:
        raise NotImplementedError
