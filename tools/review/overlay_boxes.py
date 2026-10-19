#!/usr/bin/env python
"""人工审核用：把定位层的小节裁切框画到页面上，输出一张可以直接看的图片。

这类脚本统一放 `tools/review/`：不参与 `src` 的依赖分层、不进 pytest 收集，
但和产品代码用同一套定位函数，看到的就是真实流水线切出来的框。

用法（在仓库根目录）：
    .venv/Scripts/python.exe tools/review/overlay_boxes.py --input "E:/Bass Guitar/AIAOMR/打上花火/1.png" \
        --out out/review/打上花火_p1.png
    # 多页目录也可以
    .venv/Scripts/python.exe tools/review/overlay_boxes.py --input "E:/Bass Guitar/AIAOMR/打上花火" --out out/review
    # 同时画出"模型实际收到的裁片"（按 system 分批 + 头部引用条）
    .venv/Scripts/python.exe tools/review/overlay_boxes.py --input ... --out ... --crop-plan

颜色约定：
    红   = 小节内容框（MeasureBox，x0..x1）
    蓝   = 五线谱带（System.y0..y1）
    绿   = TAB 带（System.tabY0..tabY1）
    橙   = 谱号/调号/拍号区（headerX0..headerX1）
    品红 = 实际送给模型的裁片框（--crop-plan 时）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aiaomr.kernel.config import load_config  # noqa: E402
from aiaomr.measure.crop_plan import plan  # noqa: E402
from aiaomr.score.locate.page import locate  # noqa: E402
from aiaomr.score.locate.systems import staff_lines  # noqa: E402

YELLOW = (230, 200, 30)

RED = (220, 30, 30)
BLUE = (40, 80, 220)
GREEN = (20, 150, 60)
ORANGE = (240, 140, 20)
MAGENTA = (190, 40, 190)


def _font(size: int = 22) -> ImageFont.ImageFont:
    for name in ("msyh.ttc", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_page(image_path: Path, out_path: Path, *, with_crops: bool, config) -> dict:
    # 用 locate() 而不是 locate_page()：前者跨页统一编号，标出来的号才是装配用的全局小节号。
    pageset, images = locate([str(image_path)], 3)
    page, image = pageset.pages[0], images[0]
    draw = ImageDraw.Draw(image)
    width, height = image.size
    font = _font(max(14, int(image.width / 110)))
    report = {"page": str(image_path), "systems": len(page.systems), "measures": 0}

    for system in page.systems:
        draw.rectangle([0, system.y0, width - 1, system.y1], outline=BLUE, width=2)
        draw.rectangle([0, system.tabY0, width - 1, system.tabY1], outline=GREEN, width=2)
        if system.headerX1 > system.headerX0:
            draw.rectangle(
                [system.headerX0, system.y0, system.headerX1, system.y1],
                outline=ORANGE, width=2,
            )
        for box in system.measures:
            draw.rectangle([box.x0, system.y0, box.x1, system.y1], outline=RED, width=3)
            label = f"{box.index}"
            draw.text((box.x0 + 3, system.y0 - font.size - 6), label, fill=RED, font=font)
            draw.text((box.x0 + 3, system.y1 + 2), f"sys{system.id}", fill=RED, font=_font(12))
            report["measures"] += 1

    # 有没有"画在谱面上、但定位层没认成系统"的谱表？这是最容易悄悄丢小节的地方：
    # 例如视频截图底部被播放器控件压住、TAB 带只剩两条线，配不成系统就被静默丢掉。
    arr = np.asarray(image.convert("L"))
    lines = staff_lines(arr)
    deg = page.deg or 1.0
    covered = [(system.y0, system.y1) for system in page.systems]
    orphan_groups: list[tuple[float, float]] = []
    index = 0
    while index + 5 <= len(lines):
        window = lines[index : index + 5]
        gaps = [window[k + 1] - window[k] for k in range(4)]
        uniform = max(gaps) - min(gaps) <= max(2, int(0.25 * deg))
        if uniform and 0.6 * deg <= float(np.mean(gaps)) <= 1.6 * deg:
            top, bottom = float(window[0]), float(window[-1])
            if not any(abs(top - y0) <= 2 * deg for y0, _y1 in covered):
                orphan_groups.append((top, bottom))
                y0, y1 = int(top), int(bottom)
                for x in range(0, width, 12):
                    draw.line([x, y0, min(x + 6, width), y0], fill=YELLOW, width=3)
                    draw.line([x, y1, min(x + 6, width), y1], fill=YELLOW, width=3)
                draw.text((8, y0 - font.size - 4), "未识别系统（谱表在、系统没配成）",
                          fill=YELLOW, font=font)
            index += 5
        else:
            index += 1
    report["orphanStaffGroups"] = [[round(a), round(b)] for a, b in orphan_groups]

    if with_crops:
        for index, task in enumerate(plan(image, page.systems, out_path.parent / "crops", config,
                                         page_index=0)):
            left, top, right, bottom = task.crop.box
            draw.rectangle([left, top, right, bottom], outline=MAGENTA, width=2)
            draw.text((left + 3, top + 3), task.callId, fill=MAGENTA, font=font)
            report.setdefault("crops", []).append({
                "callId": task.callId,
                "measures": [box.index for box in task.measures],
                "box": [round(value, 1) for value in task.crop.box],
            })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    report["out"] = str(out_path)
    return report


def _pages(target: Path) -> list[Path]:
    if target.is_dir():
        return sorted(p for p in target.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp"))
    return [target]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把定位层的小节裁切框画到页面上（人工审核用）")
    parser.add_argument("--input", required=True, help="图片文件或目录")
    parser.add_argument("--out", required=True, help="输出图片路径或目录")
    parser.add_argument("--crop-plan", action="store_true", help="同时画出实际送给模型的裁片框")
    args = parser.parse_args(argv)

    config = load_config("deepseek_flash")
    target = Path(args.input)
    out = Path(args.out)
    pages = _pages(target)
    if not pages:
        raise SystemExit(f"没有图片：{target}")

    reports = []
    for page_path in pages:
        if len(pages) == 1 and out.suffix.lower() in (".png", ".jpg", ".jpeg"):
            page_out = out
        else:
            page_out = out / f"{page_path.stem}_boxes.png"
        reports.append(draw_page(page_path, page_out, with_crops=args.crop_plan, config=config))

    print(json.dumps(reports, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
