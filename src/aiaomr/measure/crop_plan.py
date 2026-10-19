"""裁切规划（规格 §2.4 RD-01..RD-05；计划任务 5）。

接口粒度是小节，传输粒度是系统：这里把"一个系统"变成"一到 k 张裁片"，
每张裁片带着它覆盖的小节和几何提示，交给读谱小节层去调模型。

两条硬规则：

- 裁片统一缩放到 `crop.target_mp_min`（P0 实测：不缩放会读错）；
- 一个系统超过 `crop.target_mp_max` 时按小节边界拆开，第二张起左边拼一条谱号/调号条，
  并在提示里说明"左边这条是引用，不属于本段"（RD-03）。
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

from ..kernel.config import Config
from ..kernel.contracts import Crop, MeasureBox, MeasureTask, System



def _strip_width(deg: float, cfg: Config) -> int:
    low, high = cfg.crop.header_strip_px
    return int(min(high, max(low, round(4.0 * deg))))


def _split_groups(
    measures: list[MeasureBox],
    band_height: int,
    pitch: float,
    max_px: int,
    max_measures: int,
) -> list[list[MeasureBox]]:
    """按小节边界分组，使每组像素数不超过 `max_px`、小节数不超过 `max_measures`。"""
    groups: list[list[MeasureBox]] = []
    current: list[MeasureBox] = []
    current_px = 0.0
    for box in measures:
        px = box.width * band_height * pitch * pitch
        if current and (current_px + px > max_px or len(current) >= max_measures):
            groups.append(current)
            current, current_px = [], 0.0
        current.append(box)
        current_px += px
    if current:
        groups.append(current)
    return groups


def _resize_to_mp(image: Image.Image, target_mp: float) -> tuple[Image.Image, float]:
    """把图缩放到目标像素数，返回新图和缩放比例。"""
    pixels = image.width * image.height
    if pixels <= 0:
        return image, 1.0
    scale = math.sqrt(target_mp * 1e6 / pixels)
    if abs(scale - 1.0) < 0.01:
        return image, 1.0
    size = (max(1, int(round(image.width * scale))), max(1, int(round(image.height * scale))))
    return image.resize(size, Image.LANCZOS), size[0] * size[1] / pixels


def plan(
    page_image: Image.Image,
    systems: list[System],
    out_dir: str | Path,
    cfg: Config,
    page_index: int = 0,
) -> list[MeasureTask]:
    """`System` 列表 → `MeasureTask` 列表（每个任务一张裁片）。"""
    out_path = Path(out_dir) / "crops"
    out_path.mkdir(parents=True, exist_ok=True)

    target_mp = cfg.crop.target_mp_min
    max_px = int(round(cfg.crop.target_mp_max * 1e6))
    tasks: list[MeasureTask] = []

    for system in systems:
        if not system.measures:
            continue
        deg = (system.y1 - system.y0) / 4.0
        # RD-11：符头和数字可能画在谱表外。五线谱上下各外拓 2 格、TAB 上下各外拓 1 格，
        # 单位是 deg（R-03）；裁片从五线谱上沿外 2 格开始，到 TAB 下沿外 1 格结束。
        pad_top = int(round(cfg.crop.staff_pad_deg * deg))
        pad_bottom = int(round(cfg.crop.tab_pad_deg * deg))
        top = max(0, int(round(system.y0)) - pad_top)
        bottom = min(page_image.size[1], int(round(system.tabY1)) + pad_bottom + 1)
        band_height = bottom - top
        if band_height <= 0:
            continue

        groups = _split_groups(
            system.measures,
            band_height,
            1.0,
            max_px,
            cfg.crop.max_measures_per_call,
        )
        strip_box = (
            int(round(system.headerX0)),
            top,
            int(round(system.headerX1)),
            bottom,
        )
        strip_width = max(1, strip_box[2] - strip_box[0])
        strip_image = page_image.crop(strip_box) if strip_width > 1 else None

        for part_index, group in enumerate(groups, start=1):
            left = int(round(group[0].x0))
            right = int(round(group[-1].x1))
            if right - left < 8:
                continue
            main = page_image.crop((left, top, right, bottom))
            if part_index > 1 and strip_image is not None:
                canvas = Image.new("RGB", (strip_width + main.width, main.height), "white")
                canvas.paste(strip_image.convert("RGB"), (0, 0))
                canvas.paste(main.convert("RGB"), (strip_width, 0))
                main = canvas
                has_strip = True
            else:
                has_strip = False

            scaled, area_ratio = _resize_to_mp(main, target_mp)
            scale = math.sqrt(area_ratio)
            call_id = f"{page_index + 1:02d}s{system.id:02d}p{part_index:02d}"
            crop_path = out_path / f"{call_id}.png"
            scaled.save(crop_path)

            crop = Crop(
                path=str(crop_path),
                box=[float(left), float(top), float(right), float(bottom)],
                kind="system",
                px=int(scaled.width * scaled.height),
                deg=float(deg * scale),
                has_clef=True,
            )
            hints = {
                "page": page_index + 1,
                "system": system.id,
                "measures": [box.index for box in group],
                "stringCount": len(system.tabLines),
                "tabLines": [float(value) for value in system.tabLines],
                "deg": float(deg * scale),
                "hasStrip": has_strip,
                "stripPx": int(round(strip_width * scale)) if has_strip else 0,
                "part": part_index,
                "parts": len(groups),
            }
            tasks.append(
                MeasureTask(
                    system=system.id,
                    measures=list(group),
                    crop=crop,
                    hints=hints,
                    callId=call_id,
                )
            )
    return tasks
