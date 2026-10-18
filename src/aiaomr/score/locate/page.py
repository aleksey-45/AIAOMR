"""一页图 → `PageSet`：找系统、切小节、填谱号区（规格 §2.1）。"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageOps

from ...kernel.contracts import Page, PageSet
from ...kernel.config import Config
from .bars import find_bars
from .systems import adaptive_cut, find_systems


def load_page(path: str) -> tuple[Image.Image, np.ndarray]:
    """读图：EXIF 先转正（R-01），再给灰度数组。"""
    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return image, np.asarray(image.convert("L"))


def locate_page(path: str, page_index: int = 0) -> tuple[Page, Image.Image]:
    """定位一页：系统、小节框、谱号区范围。"""
    image, arr = load_page(path)
    systems = find_systems(arr, arr.shape[1], page_index=page_index)
    for system in systems:
        deg = (system.y1 - system.y0) / 4.0
        system.measures = find_bars(arr, system, deg)
        if system.measures:
            system.headerX0 = float(system.measures[0].x0)
            strip = min(100.0, max(40.0, 4.0 * deg))
            system.headerX1 = float(min(system.measures[0].x1, system.headerX0 + strip))
        else:
            system.headerX0 = 0.0
            system.headerX1 = float(arr.shape[1])
    page = Page(
        path=str(path),
        width=int(image.width),
        height=int(image.height),
        deg=float(np.median([(s.y1 - s.y0) / 4.0 for s in systems])) if systems else 0.0,
        systems=systems,
    )
    return page, image


def locate(pages: list[str], class_: int) -> tuple[PageSet, list[Image.Image]]:
    """多页定位，返回 `PageSet` 和与页面同序的 PIL 图（裁片时要用原图）。"""
    located: list[Page] = []
    images: list[Image.Image] = []
    for index, path in enumerate(pages):
        page, image = locate_page(path, page_index=index)
        located.append(page)
        images.append(image)
    deg = float(np.median([p.deg for p in located])) if located else 0.0
    return PageSet(pages=located, **{"class": class_}, degGlobal=deg), images
