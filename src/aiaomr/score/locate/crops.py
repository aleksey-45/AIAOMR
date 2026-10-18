"""按系统从页面图上裁图（规格 §2.4 RD-01、R-05）。

裁剪只在这里发生一次：外边距（pad）由调用方给，**禁止**在别处再叠一次 margin，
否则第一小节第一个数字会被吃掉（旧项目踩过）。
"""

from __future__ import annotations

from PIL import Image

from ...kernel.contracts import System


def system_crop(img: Image.Image, system: System, pad_px: int = 8) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """裁出一个完整系统（五线谱带 + TAB 带），返回图和原图坐标框。"""
    width, height = img.size
    top = max(0, int(round(system.y0)) - pad_px)
    bottom = min(height, int(round(system.tabY1)) + pad_px + 1)
    box = (0, top, width, bottom)
    return img.crop(box), box


def crop_region(img: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    """按原图坐标裁一块，坐标会 clamp 到图内。"""
    width, height = img.size
    left = max(0, min(width, int(box[0])))
    top = max(0, min(height, int(box[1])))
    right = max(left + 1, min(width, int(box[2])))
    bottom = max(top + 1, min(height, int(box[3])))
    return img.crop((left, top, right, bottom))
