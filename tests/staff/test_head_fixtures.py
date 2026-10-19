"""真图样本自检：manifest / PNG / bbox 三者必须对得上（计划任务 1 与补充任务 1b）。

离线：只读仓库里的 `tests/fixtures/heads/`，不碰 `E:\\Bass Guitar`，不联网。
样本从哪里来、怎么裁的，见 `tools/cut_head_fixtures.py` 与 `manifest.json`。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

HEADS = Path(__file__).resolve().parent.parent / "fixtures" / "heads"
MANIFEST_PATH = HEADS / "manifest.json"
CONTACT_SHEET = HEADS / "contact_sheet.png"

# 计划任务 1 列出的全部类别。
ALLOWED_CLASSES = frozenset(
    {
        # 音符
        "hollow_no_stem",
        "hollow_stem",
        "filled_stem",
        "beamed_1",
        "beamed_2",
        "beamed_3",
        # 休止符
        "rest_whole",
        "rest_half",
        "rest_quarter",
        "rest_eighth",
        # 修饰
        "dot_on_note",
        "dot_on_rest",
        "staccato_dot",
    }
)

# 四首歌的真值里都确实没有的类别，不硬凑；manifest.missingClasses 必须与这份名单一致。
# 依据：四首歌的真值里没有三十二分音符（连梁最多两条），也没有断音记号。
EXPECTED_MISSING = frozenset({"beamed_3", "staccato_dot"})
AVAILABLE_CLASSES = ALLOWED_CLASSES - EXPECTED_MISSING  # 11 类

# 每首歌的谱面单位（像素/间）；manifest.songs 里登记的 deg 必须与这里一致。
EXPECTED_SONGS = {"打上花火": 17.0, "NIGHT DANCER": 35.5}
# 任务 1b 从 NIGHT DANCER 补的三类；老语料（打上花火）里没有这三类。
NIGHT_DANCER_CLASSES = frozenset({"hollow_no_stem", "rest_half", "dot_on_rest"})

MIN_SAMPLES = 12
REQUIRED_FIELDS = {"file", "class", "song", "page", "measure", "measureIndex", "bbox", "deg"}


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert MANIFEST_PATH.is_file(), f"缺 manifest：{MANIFEST_PATH}"
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_shape(manifest: dict) -> None:
    assert manifest["version"] == 2
    assert manifest["marginFactor"] == pytest.approx(2.0)  # 裁剪余量 = 2 × deg
    assert set(manifest["songs"]) == set(EXPECTED_SONGS)
    for song, info in manifest["songs"].items():
        assert info["deg"] == pytest.approx(EXPECTED_SONGS[song])
        assert info["pages"], f"{song} 没登记页面尺寸"
        for size in info["pages"].values():
            assert len(size) == 2 and size[0] > 0 and size[1] > 0
    assert manifest["samples"], "manifest 里一个样本都没有"


def test_every_sample_has_required_fields(manifest: dict) -> None:
    for sample in manifest["samples"]:
        missing = REQUIRED_FIELDS - set(sample)
        assert not missing, f"{sample.get('file')} 缺字段：{missing}"
        assert isinstance(sample["note"], str) and sample["note"], "note 是给人看的说明，不能空"
        assert sample["song"] in EXPECTED_SONGS, f"{sample['file']} 的 song 不合法：{sample['song']}"
        assert sample["deg"] == pytest.approx(EXPECTED_SONGS[sample["song"]])


def test_classes_come_from_the_plan(manifest: dict) -> None:
    classes = {sample["class"] for sample in manifest["samples"]}
    assert classes <= ALLOWED_CLASSES, f"manifest 里出现了计划外的类别：{classes - ALLOWED_CLASSES}"


def test_missing_classes_are_recorded_honestly(manifest: dict) -> None:
    declared = {item["class"] for item in manifest["missingClasses"]}
    assert declared == EXPECTED_MISSING
    for item in manifest["missingClasses"]:
        assert item["reason"], f"{item['class']} 要写清楚为什么没有"
    # 缺失的类别不许偷偷出现在样本里。
    assert declared.isdisjoint(sample["class"] for sample in manifest["samples"])


def test_covers_all_available_classes(manifest: dict) -> None:
    classes = {sample["class"] for sample in manifest["samples"]}
    assert classes == AVAILABLE_CLASSES, f"少覆盖：{AVAILABLE_CLASSES - classes}"


def test_night_dancer_classes_are_complete(manifest: dict) -> None:
    # 任务 1b 补的三类必须都在，且都来自 NIGHT DANCER。
    for class_name in NIGHT_DANCER_CLASSES:
        samples = [sample for sample in manifest["samples"] if sample["class"] == class_name]
        assert samples, f"缺 {class_name} 样本"
        assert all(sample["song"] == "NIGHT DANCER" for sample in samples), f"{class_name} 应来自 NIGHT DANCER"


def test_rest_whole_sample_is_a_single_bar_whole_rest(manifest: dict) -> None:
    # 复核结论：打上花火 m51 是普通单小节里的全休止字形（矩形挂在线上），不是多小节休止条。
    samples = [sample for sample in manifest["samples"] if sample["class"] == "rest_whole"]
    assert samples, "缺全休止样本"
    assert any("单小节" in sample["note"] for sample in samples), "note 里要写明这是单小节的全休止"


def test_sample_count(manifest: dict) -> None:
    assert len(manifest["samples"]) >= MIN_SAMPLES


def test_files_exist_and_are_unique(manifest: dict) -> None:
    names = [sample["file"] for sample in manifest["samples"]]
    assert len(names) == len(set(names)), "manifest 里有重名文件"
    for name in names:
        assert (HEADS / name).is_file(), f"缺 PNG：{name}"
    on_disk = {path.name for path in HEADS.glob("*.png")} - {CONTACT_SHEET.name}
    assert on_disk == set(names), f"目录里多了没登记的 PNG：{on_disk - set(names)}"


def test_bbox_inside_page(manifest: dict) -> None:
    for sample in manifest["samples"]:
        width, height = manifest["songs"][sample["song"]]["pages"][sample["page"]]
        x0, y0, x1, y1 = sample["bbox"]
        assert 0 <= x0 < x1 <= width, f"{sample['file']} 横向越界：{sample['bbox']}"
        assert 0 <= y0 < y1 <= height, f"{sample['file']} 纵向越界：{sample['bbox']}"


def test_png_size_matches_bbox(manifest: dict) -> None:
    for sample in manifest["samples"]:
        x0, y0, x1, y1 = sample["bbox"]
        with Image.open(HEADS / sample["file"]) as image:
            assert image.size == (x1 - x0, y1 - y0), f"{sample['file']} 尺寸与 bbox 不一致"


def test_png_contains_ink(manifest: dict) -> None:
    # 每张图里必须真有墨迹：最暗像素够黑，且深色像素占比不为零。
    for sample in manifest["samples"]:
        array = np.asarray(Image.open(HEADS / sample["file"]).convert("L"))
        dark = float((array < 100).mean())
        assert int(array.min()) < 80, f"{sample['file']} 没有深色墨迹"
        assert dark > 0.005, f"{sample['file']} 深色像素占比 {dark:.4f} 太低，像空图"


def test_page_and_measure_are_consistent(manifest: dict) -> None:
    for sample in manifest["samples"]:
        assert sample["page"] in manifest["songs"][sample["song"]]["pages"]
        assert 1 <= sample["measure"] <= 107
        # 印刷小节号与 GP5 小节号一致，manifest 里两个字段同值。
        assert sample["measureIndex"] == sample["measure"]


def test_contact_sheet_is_readable() -> None:
    assert CONTACT_SHEET.is_file(), "缺 contact_sheet.png"
    with Image.open(CONTACT_SHEET) as image:
        # 28 个样本按 6 列排，至少 5 行；比任务 1 的那张（1200×662）更高。
        assert image.width >= 1200 and image.height >= 800, "contact_sheet 太小，看不清每格"
