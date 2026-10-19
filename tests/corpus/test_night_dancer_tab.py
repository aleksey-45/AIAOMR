"""NIGHT DANCER 的 TAB 回归（离线；需要先跑过一次真实读数）。

数据：`out/nd-check/measures/`（真实调用录下的模型读数）与
`out/p1/NIGHT DANCER/truth.json`（从 GPX 真值导出的逐小节事实）。
没有这两份运行时产物时跳过；它们是 `out/` 下的证据，不入库。

结论口径（2026-10-19 实测）：
- 品数（忽略弦号）92.6% 的小节完全一致；
- 弦号 + 品数 38.2% 完全一致——弦号归属是当前的主要缺口，见 `tools/review/compare_tab.py`。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "review" / "compare_tab.py"
MEASURES = Path("out/nd-check/measures")
TRUTH = Path("out/p1/NIGHT DANCER/truth.json")

pytestmark = pytest.mark.skipif(
    not (MEASURES.exists() and TRUTH.exists()),
    reason="需要 out/nd-check/measures 与 out/p1/NIGHT DANCER/truth.json（真实读数录制）",
)


def _report() -> dict:
    spec = importlib.util.spec_from_file_location("compare_tab_corpus", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reads = module._reads(MEASURES)
    truth = module._truth_measures(TRUTH)
    return module.compare(reads, truth)


def test_every_non_rest_truth_measure_is_covered() -> None:
    """对齐之后，真值里所有非空小节都必须有对应的展示小节（不能静默丢小节）。"""
    report = _report()

    assert report["missingNonRest"] == []
    assert report["displayedBars"] == 81
    assert report["truthMeasures"] == 102


def test_frets_match_at_least_90_percent() -> None:
    """只比品数（不管弦号）时，至少 90% 的非空小节完全一致（当前实测 92.6%）。"""
    report = _report()
    checked = report["tabCompared"]

    assert checked >= 60
    assert report["fretExact"] / checked >= 0.90


@pytest.mark.xfail(strict=True, reason="弦号归属未修：弦+品完全一致当前只有 38.2%")
def test_string_and_fret_must_be_perfect_for_now() -> None:
    """目标：每一小节的（弦号，品数）都与真值一致。当前不成立，先记为已知缺口。"""
    report = _report()
    checked = report["tabCompared"]

    assert report["tabExact"] == checked
