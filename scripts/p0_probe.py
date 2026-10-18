#!/usr/bin/env python
"""P0 probe：用真图实测三个参数（裁片多大、清晰度多低还能读、一次调用放几个小节）。

一次性脚本，不属于产品代码。用法：

    DEEPSEEK_API_KEY=... python scripts/p0_probe.py --out docs/p0-results.md

被测对象：打上花火第 1 页的第一个系统（7 小节，谱线间距 17.25 px）。
真值：旧项目交付时逐小节核过的读数（打上花火/read/sys01.json），只用来算"读对几成"，
不会出现在任何提示词里。

变体：
  * 一张图（整系统）对七张图（逐小节，左边拼谱号条）；
  * 同一张图缩放到不同像素量，看读数从哪一档开始错；
  * thinking 开、关各一次。

产出：`docs/p0-results.md`（人看）与 `out/p0/`（裁片、原始响应、`results.json`）。
"""

import argparse
import base64
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
# 人民币 / 百万 token，谷价（闲时）。峰时 = 谷价 × 2。
RATES = {"miss": 1.0, "hit": 0.02, "out": 4.0}

PREFIX = """You read bass guitar tablature from images. Reply with one JSON object and nothing else.
Image layout: a 5-line notation staff on top and a 4-line TAB staff below. TAB lines from top
to bottom are strings 4, 3, 2, 1; string 1 is the lowest-pitched string. Tuning is E1 A1 D2 G2
(MIDI 28, 33, 38, 43). A fret digit sits on one TAB line: one printed digit = one note. A
notehead with no digit is a tie continuation and must not be invented.
Output schema:
{"measures":[{"index":1,"beats":[{"duration":"whole|half|quarter|eighth|16th|32nd","dots":0,"rest":false,"notes":[{"string":2,"fret":3,"pitch":41}]}]}]}
Rules: read every requested measure in order; if something is unreadable set "unreadable": true
instead of guessing; do not explain; do not write files.
"""

TUNING = [28, 33, 38, 43]


def load_gray(path):
    im = Image.open(path).convert("L")
    return np.asarray(im).astype(np.float64)


def row_groups(mask, frac):
    cnt = mask.sum(axis=1)
    n = mask.shape[1]
    idx = [i for i, c in enumerate(cnt) if c > frac * n]
    groups = []
    for i in idx:
        if groups and i - groups[-1][-1] <= 3:
            groups[-1].append(i)
        else:
            groups.append([i])
    return [int(np.mean(g)) for g in groups]


def staff_rows(band, frac=0.6):
    cut = max(60.0, min(200.0, float(np.percentile(band, 80)) - 60.0))
    return row_groups(band < cut, frac), cut


def bar_columns(band, rows, cut, measures_expected):
    """小节线：在读 TAB 的那几条线的窗口里，找贯穿的竖线。"""
    if len(rows) < 8:
        raise SystemExit(f"只找到 {len(rows)} 条谱线（应至少 8 条）：{rows}")
    tab = rows[5:]
    lo = max(0, tab[0] - 6)
    hi = min(band.shape[0], tab[-1] + 7)
    sub = band[lo:hi] < cut
    cov = sub.sum(axis=0) / sub.shape[0]
    cand = np.where(cov > 0.85)[0]
    groups = []
    for c in cand:
        if groups and c - groups[-1][-1] <= 4:
            groups[-1].append(c)
        else:
            groups.append([c])
    cols = [int(np.mean(g)) for g in groups]
    # 多小节休止条、反复记号会带出贯穿 TAB 的竖线，短于半个小节宽的一律当噪声去掉
    if len(cols) > 2:
        gaps = [b - a for a, b in zip(cols, cols[1:])]
        med = float(np.median(gaps))
        cols = [c for i, c in enumerate(cols)
                if not (i + 1 < len(cols) and cols[i + 1] - c < 0.5 * med)]
    if len(cols) != measures_expected + 1:
        raise SystemExit(f"测到 {len(cols)} 条小节线，但真值是 {measures_expected + 1} 条：{cols}")
    return cols


def image_tokens(px):
    return max(180, int(1024 * max(0.296e6, min(1.69e6, px)) / 1.69e6))


def to_data_url(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def cost_cny(usage):
    hit = int(usage.get("prompt_cache_hit_tokens", 0))
    miss = int(usage.get("prompt_cache_miss_tokens", 0)) or int(usage.get("prompt_tokens", 0)) - hit
    out = int(usage.get("completion_tokens", 0))
    return round((miss * RATES["miss"] + hit * RATES["hit"] + out * RATES["out"]) / 1e6, 6)


def call_api(key, images, text, thinking=True, max_tokens=6000, retries=1):
    content = [{"type": "text", "text": text}]
    for img in images:
        content.append({"type": "image_url", "image_url": {"url": to_data_url(img), "detail": "original"}})
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
        "temperature": 0,
        "thinking": {"type": "enabled" if thinking else "disabled"},
    }
    last = None
    for _ in range(retries + 1):
        t0 = time.time()
        try:
            r = requests.post(
                API,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                json=body,
                timeout=300,
            )
            ms = int((time.time() - t0) * 1000)
            data = r.json()
        except Exception as exc:  # noqa: BLE001 - 探针要把失败也记下来
            last = {"error": repr(exc), "ms": int((time.time() - t0) * 1000)}
            time.sleep(2)
            continue
        if r.status_code != 200:
            last = {"error": f"HTTP {r.status_code}: {str(data)[:300]}", "ms": ms}
            time.sleep(2)
            continue
        return {
            "content": data["choices"][0]["message"].get("content") or "",
            "usage": data.get("usage", {}),
            "ms": ms,
            "status": 200,
        }
    return last


def load_truth(path):
    data = json.load(open(path, encoding="utf-8"))
    out = {}
    for m in data["measures"]:
        pairs = set()
        for beat in m.get("beats", []):
            for note in beat.get("notes", []):
                pairs.add((int(note["string"]), int(note["fret"])))
        out[int(m["measure"])] = pairs
    return out


def model_sets(parsed):
    out = {}
    for m in parsed.get("measures", []):
        pairs = set()
        for beat in m.get("beats", []):
            for note in beat.get("notes", []):
                if "string" in note and "fret" in note:
                    pairs.add((int(note["string"]), int(note["fret"])))
        out[int(m.get("index", 0))] = pairs
    return out


def evaluate(truth, content):
    try:
        parsed = json.loads(content)
    except Exception:  # noqa: BLE001
        return {"json": False, "measures": 0, "exact": 0, "exact_flip": 0,
                "wrong_pairs": -1, "pitch_bad": -1}
    got = model_sets(parsed)
    got_flip = {idx: {(5 - s, f) for s, f in pairs} for idx, pairs in got.items()}
    exact = exact_flip = wrong = wrong_flip = 0
    for idx, want in truth.items():
        have = got.get(idx)
        have_flip = got_flip.get(idx)
        if have == want:
            exact += 1
        if have_flip == want:
            exact_flip += 1
        wrong += len((have or set()) ^ want)
        wrong_flip += len((have_flip or set()) ^ want)
    pitch_bad = 0
    for m in parsed.get("measures", []):
        for beat in m.get("beats", []):
            for note in beat.get("notes", []):
                s, f = note.get("string"), note.get("fret")
                if not isinstance(s, int) or not isinstance(f, int) or not (1 <= s <= 4):
                    pitch_bad += 1
                    continue
                if "pitch" in note and note["pitch"] != TUNING[s - 1] + f:
                    pitch_bad += 1
    return {"json": True, "measures": len(parsed.get("measures", [])),
            "exact": exact, "exact_flip": exact_flip,
            "wrong_pairs": wrong, "wrong_pairs_flip": wrong_flip,
            "pitch_bad": pitch_bad, "parsed": parsed}


def resize_to(img, target_mp):
    native = img.width * img.height
    scale = (target_mp * 1e6 / native) ** 0.5
    size = (max(1, int(round(img.width * scale))), max(1, int(round(img.height * scale))))
    return img.resize(size, Image.LANCZOS)


def measure_boxes(band, bars, header_px):
    rows, _ = staff_rows(band)
    note, tab = rows[:5], rows[5:]
    top = note[0] - 12
    bottom = tab[-1] + 12
    boxes = []
    for i in range(len(bars) - 1):
        l = max(0, bars[i] - 4)
        r = min(band.shape[1], bars[i + 1] + 4)
        boxes.append((l, top, r, bottom))
    header = (0, top, min(header_px, bars[0] + 4), bottom)
    return boxes, header, note, tab


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", default=r"E:\Bass Guitar\AIAOMR\打上花火\1.png")
    ap.add_argument("--truth", default=r"E:\Bass Guitar\AIAOMR\打上花火\read\sys01.json")
    ap.add_argument("--y0", type=int, default=151)
    ap.add_argument("--y1", type=int, default=514)
    ap.add_argument("--x0", type=int, default=68)
    ap.add_argument("--x1", type=int, default=2502)
    ap.add_argument("--measures", type=int, default=7)
    ap.add_argument("--header-px", type=int, default=240)
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="docs/p0-results.md")
    ap.add_argument("--raw", default="out/p0/results.json")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise SystemExit("缺少 DEEPSEEK_API_KEY 环境变量")

    gray = load_gray(args.image)
    band = gray[args.y0:args.y1, args.x0:args.x1]
    band_img = Image.fromarray(band.astype(np.uint8))
    rows, cut = staff_rows(band)
    bars = bar_columns(band, rows, cut, args.measures)
    boxes, header_box, rows, tab = measure_boxes(band, bars, args.header_px)
    truth = load_truth(args.truth)
    deg = (rows[4] - rows[0]) / 4.0
    native_mp = band_img.width * band_img.height / 1e6
    print(f"系统 {band_img.width}x{band_img.height} = {native_mp:.2f}MP  deg={deg:.2f}px  "
          f"小节线 {[b + args.x0 for b in bars]}  小节数 {len(boxes)}")

    outdir = ROOT / "out" / "p0"
    outdir.mkdir(parents=True, exist_ok=True)
    band_img.save(outdir / "system.png")
    for i, box in enumerate(boxes):
        band_img.crop(box).save(outdir / f"m{i + 1}.png")
    band_img.crop(header_box).save(outdir / "header.png")

    single = band_img
    seven = []
    strip = band_img.crop(header_box)
    for box in boxes:
        m = band_img.crop(box)
        canvas = Image.new("RGB", (strip.width + m.width, m.height), "white")
        canvas.paste(strip.convert("RGB"), (0, 0))
        canvas.paste(m.convert("RGB"), (strip.width, 0))
        seven.append(canvas)

    suffix_a = f"Read measures 1 to {len(boxes)} from the single image."
    suffix_b = (f"There are {len(boxes)} images; image i corresponds to measure i, 1-based. "
                f"Read all {len(boxes)} measures.")

    # 长条裁片按小节中线拆成两张（右图左侧拼谱号条），看是否比整条更容易读
    mid = bars[len(bars) // 2]
    left_img = band_img.crop((0, boxes[0][1], mid + 4, boxes[0][3]))
    right_raw = band_img.crop((max(0, mid - 4), boxes[0][1], band_img.width, boxes[0][3]))
    right_img = Image.new("RGB", (strip.width + right_raw.width, right_raw.height), "white")
    right_img.paste(strip.convert("RGB"), (0, 0))
    right_img.paste(right_raw.convert("RGB"), (strip.width, 0))
    split_k = len(bars) // 2
    suffix_split = (f"Image 1 contains measures 1 to {split_k}. Image 2 contains measures "
                    f"{split_k + 1} to {len(boxes)}; its left strip is a clef/key reference, not music.")

    variants = []
    for rep in range(1, 4):
        variants.append((f"A_native_rep{rep}", [single], suffix_a, False, 4000))
    for rep in range(1, 4):
        variants.append((f"B_seven_rep{rep}", seven, suffix_b, False, 4500))
    for mp in (0.45, 0.70, 1.30, 1.60):
        variants.append((f"A_{mp:.2f}mp", [resize_to(single, mp)], suffix_a, False, 4000))
    for rep in range(1, 4):
        variants.append((f"A_split2_rep{rep}", [left_img, right_img], suffix_split, False, 4500))

    if args.only:
        variants = [v for v in variants if v[0] == args.only]
        if not variants:
            raise SystemExit(f"--only 没有匹配的变体: {args.only}")

    rows_out = []
    for name, imgs, suffix, thinking, max_tokens in variants:
        print(f"→ {name} ({len(imgs)} 张图, thinking={'on' if thinking else 'off'}) ...", flush=True)
        res = call_api(key, imgs, PREFIX + suffix, thinking=thinking, max_tokens=max_tokens)
        px = sum(i.width * i.height for i in imgs)
        tok_est = sum(image_tokens(i.width * i.height) for i in imgs)
        row = {
            "variant": name,
            "images": len(imgs),
            "mp_each": [round(i.width * i.height / 1e6, 3) for i in imgs],
            "image_tokens_est": tok_est,
            "thinking": thinking,
        }
        if "error" in res:
            row.update({"json": False, "measures": 0, "exact": 0, "exact_flip": 0,
                        "wrong_pairs": -1, "wrong_pairs_flip": -1,
                        "pitch_bad": -1, "error": res["error"], "ms": res["ms"], "cost_cny": 0.0,
                        "usage": {}})
        else:
            ev = evaluate(truth, res["content"])
            row.update({
                "json": ev["json"],
                "measures": ev["measures"],
                "exact": ev["exact"],
                "exact_flip": ev["exact_flip"],
                "wrong_pairs": ev["wrong_pairs"],
                "wrong_pairs_flip": ev.get("wrong_pairs_flip", -1),
                "pitch_bad": ev["pitch_bad"],
                "usage": res["usage"],
                "ms": res["ms"],
                "cost_cny": cost_cny(res["usage"]),
                "raw": res["content"],
            })
        rows_out.append(row)
        if "raw" in row:
            (outdir / f"raw_{name}.json").write_text(row["raw"], encoding="utf-8")
        print(f"   json={row['json']} measures={row['measures']} "
              f"exact={row['exact']}/{len(truth)} (flip {row.get('exact_flip', 0)}) "
              f"wrong={row['wrong_pairs']} usage={row.get('usage')} {row['ms']}ms "
              f"¥{row.get('cost_cny', 0):.4f}", flush=True)
        raw_path = ROOT / args.raw
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(
            json.dumps(rows_out, ensure_ascii=False, indent=1), encoding="utf-8")

    beijing = timezone(timedelta(hours=8))
    now = datetime.now(beijing)
    total = sum(r.get("cost_cny", 0) for r in rows_out)
    lines = [
        "# P0 实测结果",
        "",
        f"- 生成时间：{now.strftime('%Y-%m-%d %H:%M')}（北京时间，谷价口径）",
        f"- 被测图：`{args.image}` 的系统框 y={args.y0}..{args.y1}，x={args.x0}..{args.x1}",
        f"- 系统：{band_img.width}×{band_img.height} = {native_mp:.2f} MP，谱线间距 {deg:.2f} px，"
        f"{len(boxes)} 小节",
        f"- 真值：`{args.truth}`（旧项目交付时逐小节核过的读数，只用于打分）",
        f"- 共计 {len(rows_out)} 次调用，合计 ¥{total:.4f}",
        "",
        "| 变体 | 图数 | 每图像素(MP) | 图像 token(估) | 提示 token | 命中 token | 输出 token | 耗时(s) | JSON | 小节数 | 一致(原) | 一致(翻转) | 错配音对(原) | 成本(元) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows_out:
        u = r.get("usage") or {}
        lines.append(
            f"| {r['variant']} | {r['images']} | {', '.join(str(x) for x in r['mp_each'])} | "
            f"{r['image_tokens_est']} | {u.get('prompt_tokens', '')} | "
            f"{u.get('prompt_cache_hit_tokens', '')} | {u.get('completion_tokens', '')} | "
            f"{r['ms'] / 1000:.1f} | {'是' if r['json'] else '否'} | {r['measures']} | "
            f"{r['exact']}/{len(truth)} | {r.get('exact_flip', 0)}/{len(truth)} | "
            f"{r['wrong_pairs']} | ¥{r.get('cost_cny', 0):.4f} |"
        )
    lines += [
        "",
        "## 逐次调用记录",
        "",
        f"原始响应与用量见 `{args.raw}`，裁片见 `out/p0/`。",
        "",
        "## 结论（待填）",
        "",
        "参数改动见 `configs/default.toml`。",
        "",
    ]
    out = ROOT / args.out
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"写出 {out}")


if __name__ == "__main__":
    main()
