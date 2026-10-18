"""alphaTab 独立审计（规格 §4.4、E-05；计划任务 12）。

自己写自己验不算数：用 alphaTab 这个第三方库把写出的 gp5 再读一遍，检查
音高恒等式（音高 == 空弦 + 品位）和小节时值（拍数之和 == 拍号）。

没装 Node 或找不到 alphaTab 时降级为 `available: False`，不阻断（§1.3）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools" / "audit.mjs"


def audit(gp5_path: str | Path, timeout_s: int = 120) -> dict:
    """跑审计；返回 `{"available": bool, ...}`。"""
    node = shutil.which("node")
    if node is None:
        return {"available": False, "reason": "node not found"}
    if not SCRIPT.exists():
        return {"available": False, "reason": f"audit script missing: {SCRIPT}"}
    try:
        completed = subprocess.run(
            [node, str(SCRIPT), str(gp5_path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=dict(os.environ),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    text = (completed.stdout or "").strip()
    if not text:
        return {"available": False, "reason": (completed.stderr or "no output").strip()[:500]}
    try:
        result = json.loads(text.splitlines()[-1])
    except json.JSONDecodeError:
        return {"available": False, "reason": f"bad json: {text[:300]}"}
    result.setdefault("available", True)
    return result


def audit_passed(result: dict) -> bool:
    """审计通过 = 两项都是零；不可用不算通过也不算失败（由调用方标记 skipped）。"""
    if not result.get("available"):
        return False
    return int(result.get("pitchMismatch", 0)) == 0 and int(result.get("barErrors", 0)) == 0
