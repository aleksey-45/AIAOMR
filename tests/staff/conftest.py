"""真图样本夹具（`tests/fixtures/heads/`）→ `GeoContext` 的公共装配。

离线：只读仓库里的 fixture 文件，不碰 `E:\\Bass Guitar`。
做法：读 PNG → 在裁剪图内部找谱线行（行灰度中位数明显偏暗、且能落在同一等距网格上）→
按整条线厚抹出 `beam_dark` → 手工构造 `GeoContext`（deg 取 manifest 里那条样本的值）。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from aiaomr.kernel.config import StaffConfig, load_staff_config
from aiaomr.score.locate.systems import adaptive_cut
from aiaomr.score.staff.context import GeoContext

HEADS = Path(__file__).resolve().parent.parent / "fixtures" / "heads"
MANIFEST_PATH = HEADS / "manifest.json"


@pytest.fixture(scope="session")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def staff_config() -> StaffConfig:
    """判据的真实配置（`configs/default.toml` 的 staff.*），不在测试里另写一份阈值。"""
    return load_staff_config()


def samples_of(manifest: dict, *classes: str) -> list[dict]:
    return [sample for sample in manifest["samples"] if sample["class"] in classes]


def staff_lines(gray: np.ndarray, deg: float) -> tuple[list[int], int]:
    """返回（谱线中心行的窗口 y 列表, 线厚）。

    真图样本是视频/导出图的裁剪，行二值覆盖率会被压缩噪声和叠加层打乱，所以按"行灰度中位数"
    找暗行，再用"能不能落在同一个 deg 等距网格上"把符头/横梁行筛掉。
    """
    medians = np.median(gray.astype(float), axis=1)
    background = float(np.median(medians))
    dark_level = float(np.percentile(medians, 5))
    threshold = background - 0.25 * (background - dark_level)
    rows = [int(row) for row in np.flatnonzero(medians < threshold)]
    groups: list[list[int]] = []
    for row in rows:
        if groups and row - groups[-1][-1] <= 3:
            groups[-1].append(row)
        else:
            groups.append([row])
    centers = [float(np.mean(group)) for group in groups]
    thickness = int(round(float(np.median([len(group) for group in groups])))) if groups else 1
    if not centers:
        return [], thickness
    # 谱线中心应当共享同一个"deg 周期内的相位"
    phases = [(center / deg) % 1.0 for center in centers]
    buckets = [round(phase, 1) for phase in phases]
    best_bucket = max(set(buckets), key=buckets.count)
    kept = [
        int(round(center))
        for center, bucket in zip(centers, buckets)
        if min(abs(bucket - best_bucket), 1.0 - abs(bucket - best_bucket)) <= 0.15
    ]
    return kept, thickness


def context_of(sample: dict) -> GeoContext:
    """把一个 fixture 样本装成 `GeoContext`（窗口坐标就是裁剪图坐标）。"""
    gray = np.asarray(Image.open(HEADS / sample["file"]).convert("L"))
    deg = float(sample["deg"])
    dark = gray < adaptive_cut(gray)
    line_rows, thickness = staff_lines(gray, deg)
    half = max(1, thickness // 2)
    beam_dark = dark.copy()
    for row in line_rows:
        beam_dark[max(0, row - half - 1) : row + half + 2, :] = False
    return GeoContext(
        dark=dark,
        beam_dark=beam_dark,
        line_rows=line_rows,
        deg=deg,
        left=0,
        top=0,
        width=dark.shape[1],
        height=dark.shape[0],
    )


@pytest.fixture(scope="session")
def context_for():
    """样本 → GeoContext 的构造函数（fixture 里不能直接 import conftest 函数）。"""
    return context_of
