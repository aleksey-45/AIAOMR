"""裁切规划的测试（规格 §2.4 RD-02/03；计划任务 5）。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from aiaomr.kernel.config import load_config
from aiaomr.measure.crop_plan import plan
from aiaomr.score.locate.bars import find_bars
from tests.fixtures.pages import one_system_page, system_of


def _tasks(tmp_path: Path, width: int, height: int, deg: int, bars: tuple[int, ...]):
    arr, bands = one_system_page(width=width, height=height, deg=deg, bars=bars)
    system = system_of(bands, tab_spacing=max(12, int(deg * 1.5)), page_width=width)
    system.measures = find_bars(arr, system, deg=float(deg))
    image = Image.fromarray(arr).convert("RGB")
    cfg = load_config("deepseek_flash")
    return plan(image, [system], tmp_path, cfg)


def test_small_system_is_upscaled_to_target(tmp_path: Path) -> None:
    """小系统必须上采样到 1.6 MP（P0 实测）。"""
    tasks = _tasks(tmp_path, width=1600, height=420, deg=12, bars=(60, 500, 940, 1380))

    assert len(tasks) == 1
    crop = tasks[0].crop
    assert abs(crop.px / 1.6e6 - 1.0) <= 0.02
    assert crop.has_clef is True
    assert Path(crop.path).exists()


def test_wide_system_is_split_with_header_strip(tmp_path: Path) -> None:
    """超过 1.6 MP 的系统按小节边界拆开，第二张左边拼谱号条，并在提示里说明。"""
    tasks = _tasks(tmp_path, width=3000, height=900, deg=60, bars=(100, 800, 1500, 2200, 2900))

    assert len(tasks) == 2
    for task in tasks:
        assert abs(task.crop.px / 1.6e6 - 1.0) <= 0.05
    assert tasks[0].hints["hasStrip"] is False
    assert tasks[1].hints["hasStrip"] is True
    assert tasks[1].hints["stripPx"] > 0
    # 拆分不能改变小节归属
    assert [box.index for task in tasks for box in task.measures] == [1, 2, 3, 4]


def test_crop_keeps_staff_and_tab_padding(tmp_path: Path) -> None:
    """RD-11：五线谱上方留 40%（加线/高把位），TAB 下方留 25%（品数数字）。"""
    arr, bands = one_system_page(width=900, height=560, deg=12, bars=(60, 400, 740))
    system = system_of(bands, tab_spacing=18, page_width=900)
    system.measures = find_bars(arr, system, deg=12.0)
    image = Image.fromarray(arr).convert("RGB")
    cfg = load_config("deepseek_flash")

    tasks = plan(image, [system], tmp_path, cfg)

    content = system.tabY1 - system.y0
    pad_top = max(4, int(round(content * cfg.crop.staff_pad_ratio)))
    pad_bottom = max(4, int(round(content * cfg.crop.tab_pad_ratio)))
    assert (cfg.crop.staff_pad_ratio, cfg.crop.tab_pad_ratio) == (0.40, 0.25)
    assert tasks
    left, top, right, bottom = tasks[0].crop.box
    assert top == max(0, int(round(system.y0)) - pad_top)
    assert bottom == min(image.size[1], int(round(system.tabY1)) + pad_bottom + 1)
