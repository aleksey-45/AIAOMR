"""从「打上花火」「NIGHT DANCER」真图裁符头 / 休止符 / 附点样本，入库 `tests/fixtures/heads/`。

计划：`docs/superpowers/plans/2026-10-18-aiaomr-v3-p2-heads.md` 任务 1 与补充任务 1b。

做法：样本清单（歌名、页面、紧贴符号的像素框、类别）写在本文件里；脚本按清单裁 PNG，
同时生成 `manifest.json` 与一张 `contact_sheet.png`（每格标 class / 歌 / 小节，给 Lead 复核）。
裁剪框在清单的紧框基础上四边各留 2×deg（打上花火 deg≈17，NIGHT DANCER deg≈35.5），
符干 / 横梁 / 附点都算在紧框里，所以不会缺胳膊少腿。

幂等：不缩放、不重采样符号本身，PNG 用固定参数写，连续跑两次得到同样的字节。

用法（仓库根目录）：
    .venv/Scripts/python.exe tools/cut_head_fixtures.py
    .venv/Scripts/python.exe tools/cut_head_fixtures.py --root "E:/Bass Guitar/AIAOMR"
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = Path(r"E:\Bass Guitar\AIAOMR")
DEFAULT_OUT = ROOT / "tests" / "fixtures" / "heads"

# 每首歌的谱面单位（像素/间），实测值，用来算裁剪余量 = 2×deg。
SONG_DEG = {"打上花火": 17.0, "NIGHT DANCER": 35.5}
MARGIN_FACTOR = 2.0

# ---------------------------------------------------------------------------
# 样本清单：坐标是原图像素，紧贴符号（含符干 / 横梁 / 附点），裁剪时再加 2×deg 余量。
# 类别按计划任务 1：音符 6 类、休止 4 类、修饰 3 类。measure 是图上印的小节号，与 GP5
# 小节号一致。打上花火的样本来自页面 1/2/3（任务 1）；NIGHT DANCER 的样本补全音符 /
# 二分休止 / 附点休止（任务 1b），来自页面 1/2。
# ---------------------------------------------------------------------------
SAMPLES = [
    # ===================== 打上花火（任务 1 的样本，原样保留） =====================
    # --- 音符 ---
    {
        "case": "p1_m17_a",
        "song": "打上花火",
        "page": "1.png", "class": "hollow_stem", "measure": 17,
        "bbox": [587, 214, 611, 283],
        "note": "二分音符：空心符头 + 符干向上，带起始延音线（m17 第一拍）",
    },
    {
        "case": "p1_m18_a",
        "song": "打上花火",
        "page": "1.png", "class": "hollow_stem", "measure": 18,
        "bbox": [887, 247, 909, 316],
        "note": "二分音符：空心符头 + 符干向下（m18 第一拍）",
    },
    {
        "case": "p2_m52_a",
        "song": "打上花火",
        "page": "2.png", "class": "hollow_stem", "measure": 52,
        "bbox": [300, 477, 322, 546],
        "note": "二分音符：空心符头 + 符干向上（m52 第一拍）",
    },
    {
        "case": "p1_m32_a",
        "song": "打上花火",
        "page": "1.png", "class": "filled_stem", "measure": 32,
        "bbox": [1860, 981, 1884, 1051],
        "note": "四分音符：实心符头 + 符干，无附点无符尾（m32 第一拍）",
    },
    {
        "case": "p2_m53_a",
        "song": "打上花火",
        "page": "2.png", "class": "filled_stem", "measure": 53,
        "bbox": [598, 477, 621, 546],
        "note": "四分音符：实心符头 + 符干向上（m53 第一拍）",
    },
    {
        "case": "p2_m53_b",
        "song": "打上花火",
        "page": "2.png", "class": "filled_stem", "measure": 53,
        "bbox": [668, 469, 690, 536],
        "note": "四分音符：实心符头 + 符干向上（m53 第二拍）",
    },
    {
        "case": "p2_m57_c",
        "song": "打上花火",
        "page": "2.png", "class": "beamed_1", "measure": 57,
        "bbox": [2341, 489, 2423, 553],
        "note": "连梁组（一条梁）：两个八分音符，符干向上，梁在顶上（m57 第四拍）",
    },
    {
        "case": "p3_m71_a",
        "song": "打上花火",
        "page": "3.png", "class": "beamed_1", "measure": 71,
        "bbox": [2088, 131, 2165, 202],
        "note": "连梁组（一条梁）：两个八分音符（m71 第一拍）",
    },
    {
        "case": "p2_m56_b",
        "song": "打上花火",
        "page": "2.png", "class": "beamed_1", "measure": 56,
        "bbox": [1747, 466, 1828, 547],
        "note": "连梁组（一条梁）：两个八分音符，梁是斜的（m56 第三拍）",
    },
    {
        "case": "p2_m57_a",
        "song": "打上花火",
        "page": "2.png", "class": "beamed_2", "measure": 57,
        "bbox": [2112, 463, 2206, 530],
        "note": "连梁组（两条梁）：附点八分 + 十六分，十六分符干上有第二条短梁（m57 第二拍）",
    },
    {
        "case": "p2_m59_a",
        "song": "打上花火",
        "page": "2.png", "class": "beamed_2", "measure": 59,
        "bbox": [1235, 858, 1306, 927],
        "note": "连梁组（两条梁）：十六分 + 附点八分，十六分符干上有第二条梁（m59 第三拍）",
    },
    {
        "case": "p2_m56_a",
        "song": "打上花火",
        "page": "2.png", "class": "beamed_2", "measure": 56,
        "bbox": [1634, 476, 1729, 547],
        "note": "连梁组（两条梁）：附点八分 + 十六分（m56 第二拍）",
    },
    # --- 休止符 ---
    {
        "case": "p2_m51_a",
        "song": "打上花火",
        "page": "2.png", "class": "rest_whole", "measure": 51,
        "bbox": [2350, 143, 2372, 151],
        "note": "全休止：挂在第四线下面的一块实心矩形；m51 是普通单小节（不是多小节休止条）",
    },
    {
        "case": "p1_m32_b",
        "song": "打上花火",
        "page": "1.png", "class": "rest_quarter", "measure": 32,
        "bbox": [2101, 998, 2121, 1051],
        "note": "四分休止：折线形符号（m32 第四拍）",
    },
    {
        "case": "p2_m55_b",
        "song": "打上花火",
        "page": "2.png", "class": "rest_quarter", "measure": 55,
        "bbox": [1427, 493, 1448, 547],
        "note": "四分休止：折线形符号（m55 第四拍）",
    },
    {
        "case": "p1_m31_a",
        "song": "打上花火",
        "page": "1.png", "class": "rest_eighth", "measure": 31,
        "bbox": [1543, 1011, 1562, 1040],
        "note": "八分休止：像数字 7 的钩形（m31 第三拍）",
    },
    {
        "case": "p3_m70_a",
        "song": "打上花火",
        "page": "3.png", "class": "rest_eighth", "measure": 70,
        "bbox": [1819, 145, 1838, 174],
        "note": "八分休止：钩形（m70 末拍）",
    },
    {
        "case": "p3_m69_a",
        "song": "打上花火",
        "page": "3.png", "class": "rest_eighth", "measure": 69,
        "bbox": [1464, 145, 1483, 174],
        "note": "八分休止：钩形（m69 末拍）",
    },
    # --- 修饰 ---
    {
        "case": "p1_m17_b",
        "song": "打上花火",
        "page": "1.png", "class": "dot_on_note", "measure": 17,
        "bbox": [745, 205, 778, 273],
        "note": "音符附点：实心符头右侧的圆点（m17 附点四分音符）",
    },
    {
        "case": "p2_m52_b",
        "song": "打上花火",
        "page": "2.png", "class": "dot_on_note", "measure": 52,
        "bbox": [455, 477, 488, 547],
        "note": "音符附点：实心符头右侧的圆点（m52 附点四分音符）",
    },
    {
        "case": "p2_m54_a",
        "song": "打上花火",
        "page": "2.png", "class": "dot_on_note", "measure": 54,
        "bbox": [1084, 469, 1117, 536],
        "note": "音符附点：实心符头右侧的圆点（m54 附点四分音符）",
    },
    # ===================== NIGHT DANCER（任务 1b 补的三类） =====================
    # --- 全音符（空心、无符干） ---
    {
        "case": "nd_m55_a",
        "song": "NIGHT DANCER",
        "page": "NIGHT DANCER#2.png", "class": "hollow_no_stem", "measure": 55,
        "bbox": [548, 4152, 610, 4186],
        "note": "全音符：空心符头、没有符干，整小节就这一个音（m55；2×deg 余量内会带一点上方印刷小节号）",
    },
    # --- 二分休止（实心矩形坐在中间线上） ---
    {
        "case": "nd_m7_a",
        "song": "NIGHT DANCER",
        "page": "NIGHT DANCER#1.png", "class": "rest_half", "measure": 7,
        "bbox": [3434, 1153, 3477, 1173],
        "note": "二分休止：实心矩形下沿坐在中间线上，后面接八分休止（m7 前两拍休止）",
    },
    {
        "case": "nd_m23_a",
        "song": "NIGHT DANCER",
        "page": "NIGHT DANCER#1.png", "class": "rest_half", "measure": 23,
        "bbox": [3384, 3415, 3426, 3435],
        "note": "二分休止：实心矩形坐在中间线上（m23 前两拍休止，后接两个四分音符）",
    },
    {
        "case": "nd_m61_a",
        "song": "NIGHT DANCER",
        "page": "NIGHT DANCER#2.png", "class": "rest_half", "measure": 61,
        "bbox": [1079, 5635, 1121, 5655],
        "note": "二分休止：实心矩形坐在中间线上（m61 第二拍，前接一个二分音符）",
    },
    # --- 附点休止（四分休止折线右侧带圆点） ---
    {
        "case": "nd_m62_a",
        "song": "NIGHT DANCER",
        "page": "NIGHT DANCER#2.png", "class": "dot_on_rest", "measure": 62,
        "bbox": [2614, 5602, 2678, 5710],
        "note": "附点四分休止：四分休止折线 + 右上方的圆点（m62 第四拍）",
    },
    {
        "case": "nd_m24_a",
        "song": "NIGHT DANCER",
        "page": "NIGHT DANCER#1.png", "class": "dot_on_rest", "measure": 24,
        "bbox": [1335, 4086, 1398, 4194],
        "note": "附点四分休止：四分休止折线 + 右上方的圆点（m24 第四拍）",
    },
    {
        "case": "nd_m22_a",
        "song": "NIGHT DANCER",
        "page": "NIGHT DANCER#1.png", "class": "dot_on_rest", "measure": 22,
        "bbox": [2530, 3382, 2593, 3490],
        "note": "附点四分休止：四分休止折线 + 右上方的圆点（m22 第四拍）",
    },
]

# 四首歌的真值里都确实没有的类别。不硬凑，写进 manifest 与报告。
MISSING_CLASSES = [
    {"class": "beamed_3", "reason": "四首歌的真值里都没有三十二分音符，连梁最多两条"},
    {"class": "staccato_dot", "reason": "四首歌的真值里都没有断音记号（staccato effect 全为假）"},
]

# 中文标签优先用系统里的中文字体，找不到就退回 PIL 默认字体（默认字体没有中文字形）。
_CJK_FONTS = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]


def _font(size: int):
    for path in _CJK_FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # 老版本 Pillow 的 load_default 不带 size
        return ImageFont.load_default()


def _page_path(root: Path, sample: dict) -> Path:
    return root / sample["song"] / sample["page"]


def _crop_box(sample: dict, page_size: tuple[int, int]) -> list[int]:
    """紧框 + 2×deg 余量，裁到页面内。"""
    width, height = page_size
    margin = int(round(MARGIN_FACTOR * SONG_DEG[sample["song"]]))
    x0, y0, x1, y1 = sample["bbox"]
    return [
        max(0, x0 - margin),
        max(0, y0 - margin),
        min(width, x1 + margin),
        min(height, y1 + margin),
    ]


def _file_name(sample: dict, seen: dict[str, int]) -> str:
    page_stem = Path(sample["page"]).stem
    if sample["song"] == "打上花火":
        tag = page_stem  # 任务 1 的老文件名保持不变
    else:
        tag = "nd" + page_stem.split("#")[-1]
    key = f"{sample['class']}_{tag}_m{sample['measure']:03d}"
    seen[key] = seen.get(key, 0) + 1
    suffix = chr(ord("a") + seen[key] - 1)
    return f"{key}_{suffix}.png"


def _save_png(image: Image.Image, path: Path) -> None:
    """固定参数的 PNG，保证同样输入得到同样字节。"""
    tmp = path.with_suffix(".png.tmp")
    image.save(tmp, format="PNG", optimize=False, compress_level=9)
    os.replace(tmp, path)


def _contact_sheet(entries: list[dict], out_path: Path) -> None:
    """所有样本拼一张图，每格下面标 class / 歌 / 小节，给 Lead 复核。"""
    thumb_height = 120
    cell_width = 220
    label_height = 46
    columns = 6
    rows = (len(entries) + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (columns * cell_width, rows * (thumb_height + label_height) + 46),
        (238, 238, 238),
    )
    draw = ImageDraw.Draw(sheet)
    font = _font(13)
    for number, entry in enumerate(entries):
        crop = Image.open(out_path.parent / entry["file"]).convert("RGB")
        scale = thumb_height / crop.height
        width = max(1, int(round(crop.width * scale)))
        thumb = crop.resize((width, thumb_height), Image.LANCZOS)
        left = (number % columns) * cell_width + (cell_width - width) // 2
        top = (number // columns) * (thumb_height + label_height) + 6
        sheet.paste(thumb, (left, top))
        draw.rectangle([left, top, left + width, top + thumb_height], outline=(180, 60, 60))
        draw.text(
            ((number % columns) * cell_width + 6, top + thumb_height + 6),
            f"{entry['class']}\n{entry['song']} m{entry['measure']}",
            fill=(20, 20, 20),
            font=font,
        )
    draw.text(
        (8, rows * (thumb_height + label_height) + 24),
        "missing classes (not in this corpus): " + ", ".join(item["class"] for item in MISSING_CLASSES),
        fill=(120, 0, 0),
        font=font,
    )
    _save_png(sheet, out_path)


def build(root: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    pages: dict[str, dict[str, list[int]]] = {}
    images: dict[tuple[str, str], Image.Image] = {}
    for sample in SAMPLES:
        key = (sample["song"], sample["page"])
        if key in images:
            continue
        image = Image.open(_page_path(root, sample)).convert("RGB")
        images[key] = image
        pages.setdefault(sample["song"], {})[sample["page"]] = [image.width, image.height]

    seen: dict[str, int] = {}
    entries = []
    for sample in SAMPLES:
        image = images[(sample["song"], sample["page"])]
        box = _crop_box(sample, image.size)
        file_name = _file_name(sample, seen)
        crop = image.crop(tuple(box))
        _save_png(crop, out_dir / file_name)
        entries.append(
            {
                "file": file_name,
                "class": sample["class"],
                "song": sample["song"],
                "page": sample["page"],
                "measure": sample["measure"],
                "measureIndex": sample["measure"],
                "bbox": box,
                "deg": SONG_DEG[sample["song"]],
                "note": sample["note"],
            }
        )

    manifest = {
        "version": 2,
        "source": "E:/Bass Guitar/AIAOMR/<song>/<page>（打上花火=视频截图；NIGHT DANCER=GP 导出图）",
        "marginFactor": MARGIN_FACTOR,
        "songs": {
            song: {"deg": SONG_DEG[song], "pages": pages[song]}
            for song in SONG_DEG
            if song in pages
        },
        "classes": sorted({entry["class"] for entry in entries}),
        "missingClasses": MISSING_CLASSES,
        "samples": entries,
    }
    manifest_path = out_dir / "manifest.json"
    tmp_path = manifest_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, manifest_path)

    _contact_sheet(entries, out_dir / "contact_sheet.png")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="裁符头/休止/附点真图样本")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="真图根目录（<root>/<song>/<page>）")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="fixture 输出目录")
    args = parser.parse_args()

    manifest = build(args.root, args.out)
    print(f"输出目录：{args.out}")
    print(f"样本：{len(manifest['samples'])} 个，覆盖 {len(manifest['classes'])} 类：{manifest['classes']}")
    print("歌曲：" + "、".join(manifest["songs"]))
    print("缺失（语料里没有，不硬凑）：" + "、".join(item["class"] for item in manifest["missingClasses"]))
    print("产物：PNG + manifest.json + contact_sheet.png")


if __name__ == "__main__":
    main()
