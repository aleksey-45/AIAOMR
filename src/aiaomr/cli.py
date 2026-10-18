"""命令行入口（规格 §2.10、§7、§8、§10）。

一条命令把一张（或一叠）谱图跑到 `.gp5`：登记输入 → 定位 → 读骨架 → 读小节 →
验算 → 装配 → 写文件 → 独立审计。

输出契约：stdout 只放事件（NDJSON），stderr 放日志；`events.ndjson` 永远落盘，
`run.finished` 全局恰好一次。退出码：0 成功、1 输入/阶段失败、2 工具失败、3 超预算、130 被中断。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from PIL import Image

from .events import Emitter, HumanRenderer
from .kernel.config import Config, ConfigError, load_config
from .kernel.contracts import Crop, MeasureResult, PageSet
from .kernel.errors import ErrorCode
from .kernel.ir import Audit, Build, IR, Meta, Source
from .measure.crop_plan import plan
from .measure.read import read_systems
from .providers.base import ProviderError
from .providers.registry import get_provider
from .score.assemble.assemble import assemble
from .score.locate.page import locate as locate_pages
from .score.skeleton.read import read_skeleton
from .score.verify.invariants import check_all
from .writers.audit import audit, audit_passed
from .writers.base import WriterError
from .writers.registry import get_writer

STAGES = ["input", "locate", "skeleton", "read", "verify", "assemble", "write", "audit"]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class _Tee:
    """同一份事件同时写字幕流和文件；两边都 flush。"""

    def __init__(self, *streams) -> None:
        self._streams = streams

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


class Reporter:
    """事件写到 `events.ndjson`（永远）与 stdout（ndjson 模式）；human 模式另打摘要。"""

    def __init__(self, out_dir: Path, fmt: str) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        self.path = out_dir / "events.ndjson"
        self._file = open(self.path, "w", encoding="utf-8", newline="\n")
        self._human = fmt == "human"
        stream = self._file if self._human else _Tee(sys.stdout, self._file)
        self.emitter = Emitter(stream)
        self.renderer = HumanRenderer() if self._human else None

    def emit(self, stage_name: str, event_name: str, level: str = "info", **data):
        record = self.emitter.emit(stage_name, event_name, level=level, **data)
        if self.renderer is not None:
            line = self.renderer.render(record)
            if line:
                print(line, flush=True)
        return record

    def close(self) -> None:
        self._file.flush()
        self._file.close()


def _sha256(paths: list[str]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _collect_pages(path: str) -> list[str]:
    target = Path(path)
    if target.is_dir():
        pages = sorted(p for p in target.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        if not pages:
            raise ConfigError(f"目录里没有图片：{target}")
        return [str(p) for p in pages]
    if not target.exists():
        raise ConfigError(f"输入不存在：{target}")
    if target.suffix.lower() not in IMAGE_SUFFIXES:
        raise ConfigError(f"不支持的输入格式：{target.suffix}")
    return [str(target)]


def _header_crop(page_image: Image.Image, pageset: PageSet, out_dir: Path) -> Crop:
    """首页头部裁片：标题、速度、拍号、调号、调弦都印在第一个系统的上方。"""
    page = pageset.pages[0]
    height = page_image.size[1]
    top = 0
    bottom = height
    if page.systems:
        bottom = min(height, int(round(page.systems[0].y0)) + 8)
    box = (0, top, int(page.width), bottom)
    if box[3] - box[1] < 8:
        box = (0, 0, int(page.width), min(height, 80))
    crop_dir = out_dir / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    path = crop_dir / "header.png"
    page_image.crop(box).save(path)
    return Crop(
        path=str(path),
        box=[float(v) for v in box],
        kind="sheet",
        px=(box[2] - box[0]) * (box[3] - box[1]),
        deg=float(page.deg),
        has_clef=True,
    )


def _load_config(args) -> Config:
    name = "deepseek_flash" if args.provider == "stub" else args.provider
    return load_config(name)


def _make_provider(args, cfg: Config, out_dir: Path):
    replay = out_dir / "calls"
    return get_provider(
        args.provider, cfg, api_key=args.api_key,
        offline_dir=replay if args.provider == "stub" else None,
    )


def _write_json(path: Path, payload) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(path)


def _block(reporter: Reporter, out_dir: Path, stage: str, code: ErrorCode, message: str) -> int:
    """阻断：留下四样东西（阻断信息、run.log、events、产物），返回退出码（§7.1）。"""
    exit_code = 2
    if code is ErrorCode.E_INPUT_UNREADABLE or code is ErrorCode.E_NO_SYSTEM:
        exit_code = 1
    if code is ErrorCode.E_BUDGET_EXCEEDED:
        exit_code = 3
    (out_dir / "run.log").write_text(
        f"{datetime.now(timezone.utc).isoformat()} BLOCKED at {stage}: {code.value} {message}\n",
        encoding="utf-8",
    )
    reporter.emit(
        stage,
        "block",
        level="error",
        code=code.value,
        message=message,
        artifacts=[str(out_dir / "ir.json"), str(out_dir / "events.ndjson")],
        resumable=True,
    )
    reporter.emit(
        "run",
        "run.finished",
        level="error",
        status="blocked",
        stage=stage,
        exitCode=exit_code,
        code=code.value,
        message=message,
        outDir=str(out_dir),
    )
    return exit_code


def _budget_block(reporter: Reporter, out_dir: Path, message: str) -> int:
    return _block(reporter, out_dir, "read", ErrorCode.E_BUDGET_EXCEEDED, message)


def run_command(args) -> int:
    fmt = args.format
    if fmt == "auto":
        fmt = "human" if sys.stdout.isatty() else "ndjson"

    try:
        cfg = _load_config(args)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    song = args.song or Path(args.input).stem
    out_dir = Path(args.out) if args.out else Path("out") / song
    out_dir = out_dir.resolve()
    reporter = Reporter(out_dir, fmt)
    started = time.monotonic()
    stage_ms: dict[str, int] = {}

    try:
        reporter.emit(
            "run", "run.started", input=args.input, class_=args.input_class, song=song,
            provider=cfg.provider.name, outDir=str(out_dir),
        )
        try:
            pages = _collect_pages(args.input)
        except ConfigError as exc:
            return _block(reporter, out_dir, "input", ErrorCode.E_INPUT_UNREADABLE, str(exc))

        stopped = False

        def stage_begin(name: str) -> float:
            reporter.emit("run", "stage.started", stage=name)
            return time.monotonic()

        def stage_end(name: str, start: float, **data) -> None:
            stage_ms[name] = int((time.monotonic() - start) * 1000)
            reporter.emit("run", "stage.finished", stage=name, durationMs=stage_ms[name], **data)

        # ---- input ----------------------------------------------------
        start = stage_begin("input")
        sha = _sha256(pages)
        _write_json(out_dir / "input.json", {
            "class": args.input_class, "kind": "image", "files": pages, "inputSha256": sha,
        })
        stage_end("input", start, files=len(pages))
        if args.until == "input":
            stopped = True

        # ---- locate ---------------------------------------------------
        if not stopped:
            start = stage_begin("locate")
            pageset_path = out_dir / "pageset.json"
            if args.resume and pageset_path.exists():
                pageset = PageSet.model_validate_json(pageset_path.read_text(encoding="utf-8"))
                images = [Image.open(page.path).convert("RGB") for page in pageset.pages]
                reporter.emit("locate", "locate.cached", file=str(pageset_path))
            else:
                pageset, images = locate_pages(pages, args.input_class)
                _write_json(pageset_path, json.loads(pageset.model_dump_json()))
            if not pageset.pages or not any(page.systems for page in pageset.pages):
                return _block(reporter, out_dir, "locate", ErrorCode.E_NO_SYSTEM, "没有找到任何合格系统")
            measures = sum(len(system.measures) for page in pageset.pages for system in page.systems)
            reporter.emit("locate", "locate.done", systems=sum(len(p.systems) for p in pageset.pages),
                          measures=measures, deg=pageset.degGlobal)
            stage_end("locate", start, systems=sum(len(p.systems) for p in pageset.pages))
            if args.until == "locate":
                stopped = True

        # ---- skeleton -------------------------------------------------
        if not stopped:
            start = stage_begin("skeleton")
            skeleton_path = out_dir / "skeleton.json"
            if args.resume and skeleton_path.exists() and "skeleton" not in args.force:
                from .kernel.contracts import Skeleton

                skeleton = Skeleton.model_validate_json(skeleton_path.read_text(encoding="utf-8"))
                reporter.emit("skeleton", "skeleton.cached", file=str(skeleton_path))
            else:
                provider = _make_provider(args, cfg, out_dir)
                header = _header_crop(images[0], pageset, out_dir)
                first_system = pageset.pages[0].systems[0]
                skeleton = read_skeleton(
                    header, provider, cfg, emit=reporter.emit,
                    hints={"page": 1, "stringCount": len(first_system.tabLines),
                           "callId": "skeleton", "title": song},
                )
                _write_json(skeleton_path, json.loads(skeleton.model_dump_json()))
            reporter.emit("skeleton", "skeleton.done", title=skeleton.title,
                          timeSignature=(skeleton.timeSignatures[0].beats if skeleton.timeSignatures else None))
            stage_end("skeleton", start)
            if args.until == "skeleton":
                stopped = True

        # ---- read -----------------------------------------------------
        results: list[MeasureResult] = []
        if not stopped:
            start = stage_begin("read")
            tasks = []
            for index, (page, image) in enumerate(zip(pageset.pages, images)):
                tasks.extend(plan(image, page.systems, out_dir / f"page{index + 1:02d}", cfg,
                                  page_index=index))
            if not tasks:
                return _block(reporter, out_dir, "read", ErrorCode.E_NO_SYSTEM, "裁切规划没有产出任务")
            provider = _make_provider(args, cfg, out_dir)
            budget = Decimal(cfg.budget.cny_per_8measures)
            total_measures = sum(len(task.measures) for task in tasks)
            cumulative = Decimal("0.0000")
            cached = 0
            pending = []
            for task in tasks:
                cache_path = out_dir / "measures" / f"{task.callId}.json"
                if args.resume and cache_path.exists() and "read" not in args.force:
                    results.append(MeasureResult.model_validate_json(cache_path.read_text(encoding="utf-8")))
                    cached += 1
                else:
                    pending.append(task)

            for task, result in zip(pending, read_systems(pending, provider, cfg, emit=reporter.emit)):
                (out_dir / "measures").mkdir(parents=True, exist_ok=True)
                (out_dir / "measures" / f"{task.callId}.json").write_text(
                    result.model_dump_json(indent=1), encoding="utf-8")
                if hasattr(provider, "cost_cny") and result.usage:
                    call_cost = provider.cost_cny(result.usage)
                    if call_cost > budget:
                        return _budget_block(
                            reporter, out_dir,
                            f"单次调用成本 {call_cost} 超过每 8 小节预算 {budget}",
                        )
                    cumulative += call_cost
                    allowed = budget * Decimal(max(1, (total_measures + 7) // 8))
                    if cumulative > allowed:
                        return _budget_block(
                            reporter, out_dir,
                            f"累计成本 {cumulative} 超过派生上限 {allowed}",
                        )
                results.append(result)

            if results and all(result.errorCode is not None for result in results):
                code = results[0].errorCode or ErrorCode.E_VLM_SCHEMA
                return _block(reporter, out_dir, "read", code, "所有调用都失败")
            reporter.emit("read", "read.done", calls=len(pending), cached=cached,
                          systems=len(pageset.pages))
            stage_end("read", start, calls=len(pending), cached=cached)
            if args.until == "read":
                stopped = True

        reads = [read for result in results for read in result.reads]
        if not stopped:
            # ---- verify ----------------------------------------------
            start = stage_begin("verify")
            alarms = check_all(reads, skeleton)
            _write_json(out_dir / "judgements.json",
                        {"alarms": [alarm.as_dict() for alarm in alarms]})
            reporter.emit("verify", "verify.done", alarms=len(alarms))
            stage_end("verify", start, alarms=len(alarms))

            # ---- assemble --------------------------------------------
            start = stage_begin("assemble")
            source = Source(**{"class": args.input_class}, kind="image", files=pages,
                             inputSha256=sha)
            meta = Meta(provider=cfg.provider.name, model=cfg.provider.model,
                        promptVersion="p0", schemaVersion="3.0",
                        generatedAt=datetime.now(timezone.utc))
            ir = assemble(reads, skeleton, alarms, source=source, meta=meta,
                          class_=args.input_class)
            reporter.emit("assemble", "assemble.done", measures=len(ir.measures))
            stage_end("assemble", start, measures=len(ir.measures))
            if args.until == "assemble":
                stopped = True

        if not stopped:
            # ---- write ------------------------------------------------
            start = stage_begin("write")
            writer = get_writer("gp5")
            gp5_path = out_dir / f"{song}.gp5"
            try:
                report = writer.write(ir, str(gp5_path))
            except WriterError as exc:
                return _block(reporter, out_dir, "write", exc.code,
                              f"{exc}: {'; '.join(exc.details[:5])}")
            reporter.emit("write", "build.written", path=str(gp5_path), bytes=report.bytes,
                          roundtrip=report.roundtrip)
            stage_end("write", start, bytes=report.bytes)
            if args.until == "write":
                stopped = True

        if not stopped:
            # ---- audit ------------------------------------------------
            start = stage_begin("audit")
            audit_result = audit(gp5_path)
            passed = audit_passed(audit_result)
            reporter.emit("audit", "audit.result", **audit_result)
            stage_end("audit", start)
            if audit_result.get("available") and not passed:
                return _block(reporter, out_dir, "audit", ErrorCode.E_AUDIT,
                              f"审计未通过：{audit_result}")
            ir = ir.model_copy(update={
                "build": Build(
                    gp5=str(gp5_path),
                    roundtrip="OK",
                    audit=Audit(
                        pitchMismatch=int(audit_result.get("pitchMismatch", 0)),
                        barErrors=int(audit_result.get("barErrors", 0)),
                    ),
                )
            })
            ir.to_json(out_dir / "ir.json")
            _write_json(out_dir / "metrics.json", {
                "stagesMs": stage_ms,
                "measures": len(ir.measures),
                "calls": sum(1 for r in results if r.errorCode is None),
                "alarms": len([alarm for alarm in alarms]) if "alarms" in locals() else 0,
                "audit": {k: audit_result.get(k) for k in ("available", "pitchMismatch", "barErrors")},
            })

        reporter.emit(
            "run", "run.finished", status="stopped" if stopped else "ok", exitCode=0,
            durationMs=int((time.monotonic() - started) * 1000), outDir=str(out_dir),
        )
        return 0
    except KeyboardInterrupt:
        (out_dir / "run.log").write_text("interrupted by user\n", encoding="utf-8")
        reporter.emit("run", "run.finished", level="warn", status="interrupted", exitCode=130,
                      durationMs=int((time.monotonic() - started) * 1000))
        return 130
    finally:
        reporter.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aiaomr", description="贝斯谱图片 → gp5")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="跑完整流程")
    run.add_argument("--input", required=True, help="图片或图片目录")
    run.add_argument("--class", dest="input_class", type=int, default=3, choices=(1, 3, 5, 6))
    run.add_argument("--song", default=None, help="曲名（默认取文件名）")
    run.add_argument("--out", default=None, help="输出目录（默认 out/<song>）")
    run.add_argument("--provider", default="deepseek_flash")
    run.add_argument("--api-key", default=None, help="仅测试用；正常从 DEEPSEEK_API_KEY 读")
    run.add_argument("--format", default="auto", choices=("auto", "human", "ndjson"))
    run.add_argument("--until", default="audit", choices=STAGES)
    run.add_argument("--resume", action="store_true", help="复用已有中间产物，已付钱的调用不重复付")
    run.add_argument("--force", nargs="*", default=[], help="强制重跑某几个阶段")
    run.add_argument("-v", "--verbose", action="count", default=0)
    run.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return run_command(args)
    parser.error(f"未知命令：{args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
