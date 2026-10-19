"""读五线谱（L3，`spec-v3.md` §2.11，规范 `docs/spec-staff.md`）。

目录与文件划分见规范 §12：一条判据一个文件，`read.py` 只做编排。
本层的产物是 `MeasureRhythm`（每小节的符号类别与时值 + abstain 理由），
不是最终结论；最终结论由装配层把几何 claim 与模型读数合并后给出。
"""

from .read import read_measure, read_page, read_system

__all__ = ["read_measure", "read_page", "read_system"]

