"""读谱小节层的入口：裁片 → 一次模型调用 → 逐小节的结构化事实（规格 §2.4）。

这一层只负责"把像素变成结构化事实并校验形状"：不判断对错，不补写任何 beat（RD-10）。
四道闸的前三道在这里：G1 请求约束（prompt 里写 schema + 几何提示）、G2 严格 json.loads、
G3 pydantic 结构校验；第四道 G4 业务不变量在验算层。

弦号翻转只在这里发生一次（RD-06b）：模型按 Guitar Pro 习惯编号（最上面那条 TAB 线是 1），
IR 约定是 1 = 最低音弦，所以 `ir_string = stringCount - model_string + 1`。
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..kernel.config import Config
from ..kernel.contracts import MeasureRead, MeasureResult, MeasureTask
from ..kernel.errors import ErrorCode
from ..kernel.ir import Beat, Digit, Evidence, Note
from ..providers.base import ImageInput, ProviderError, VisionProvider, VisionRequest
from .schema import ModelResponse, SchemaError, validate

_PROMPT_PATH = Path(__file__).parent / "prompts" / "system.md"
_MAX_REPAIR_CHARS = 500
_MAX_SCHEMA_ATTEMPTS = 2


def load_prompt(version: str = "p0") -> str:
    """读稳定前缀（逐字节不变，为了命中缓存，V-11）。"""
    return _PROMPT_PATH.read_text(encoding="utf-8").replace("{{promptVersion}}", version)


def max_tokens_for(rule: str, measures: int) -> int:
    """按 `max_tokens_rule`（形如 `400*measures+800`）算本次调用的输出上限。"""
    match = re.search(r"(\d+)\s*\*\s*measures\s*\+\s*(\d+)", rule)
    if not match:
        return 4000
    return int(match.group(1)) * max(1, measures) + int(match.group(2))


def build_suffix(task: MeasureTask, cfg: Config) -> str:
    """可变后缀：小节号、弦数、调弦、拍号、调号；稳定前缀不在这里。"""
    hints = task.hints or {}
    indices = [box.index for box in task.measures]
    parts = [
        f"Page {hints.get('page', 1)}, system {task.system}. Read measures: {', '.join(str(i) for i in indices)}.",
        f"The TAB staff has {hints.get('stringCount', 4)} lines.",
    ]
    tuning = hints.get("tuning")
    if tuning:
        parts.append(f"Tuning (MIDI, lowest string first): {', '.join(str(v) for v in tuning)}.")
    if hints.get("timeSignature"):
        parts.append(f"Current time signature: {hints['timeSignature']}.")
    if hints.get("keySignature"):
        parts.append(f"Current key signature: {hints['keySignature']}.")
    if hints.get("hasStrip"):
        parts.append("The left strip of this crop is a clef/key reference and is not part of the music.")
    return " ".join(parts)


def _convert(
    parsed: ModelResponse,
    task: MeasureTask,
    hints: dict,
) -> list[MeasureRead]:
    expected = [box.index for box in task.measures]
    got = [measure.index for measure in parsed.measures]
    if got != expected:
        raise SchemaError(f"小节号不匹配：请求 {expected}，返回 {got}")

    string_count = int(hints.get("stringCount", 4))
    tuning = hints.get("tuning") or []
    evidence = Evidence(
        system=task.system,
        crop=[float(value) for value in task.crop.box],
        call=task.callId,
    )

    reads: list[MeasureRead] = []
    for measure in parsed.measures:
        if measure.unreadable:
            reads.append(MeasureRead(index=measure.index, beats=[], unreadable=True))
            continue
        beats: list[Beat] = []
        for beat in measure.beats:
            notes: list[Note] = []
            for note in beat.notes:
                ir_string = string_count - note.string + 1
                if not 1 <= ir_string <= string_count:
                    raise SchemaError(f"弦号越界：模型给 {note.string}，弦数 {string_count}")
                pitch = tuning[ir_string - 1] + note.fret if len(tuning) == string_count else note.pitch
                digit = (
                    Digit(value=note.digit, glyphs=len(note.digit), bound=True)
                    if note.digit
                    else None
                )
                notes.append(
                    Note(
                        string=ir_string,
                        fret=note.fret,
                        tie=note.tie,
                        tieFromPrevious=note.tieFromPrevious,
                        digit=digit,
                        techniques=[],
                        pitch=pitch,
                        pitchClaim=note.pitch,
                    )
                )
            beats.append(
                Beat(
                    duration=beat.duration,
                    dots=beat.dots,
                    rest=beat.rest,
                    notes=notes,
                    prov="read",
                    evidence=evidence,
                )
            )
        reads.append(MeasureRead(index=measure.index, beats=beats, unreadable=False))
    return reads


def _read_one(task: MeasureTask, provider: VisionProvider, cfg: Config) -> MeasureResult:
    if not task.crop.has_clef:
        raise ValueError(f"裁片不含谱号区，禁止送出（RD-04）：{task.callId}")
    image_path = Path(task.crop.path)
    if not image_path.exists():
        raise ValueError(f"裁片文件不存在：{image_path}")
    image = ImageInput(image_path.read_bytes(), "image/png")

    suffix = build_suffix(task, cfg)
    attempts = 0
    last_error: SchemaError | None = None
    while attempts < _MAX_SCHEMA_ATTEMPTS:
        attempts += 1
        request = VisionRequest(
            call_id=task.callId,
            prompt_prefix=load_prompt(),
            prompt_suffix=suffix,
            images=(image,),
            max_tokens=max_tokens_for(cfg.provider.max_tokens_rule, len(task.measures)),
            thinking=bool(cfg.provider.thinking),
        )
        try:
            response = provider.read(request)
        except ProviderError as exc:
            return MeasureResult(
                callId=task.callId, reads=[], usage=None, errorCode=exc.code
            )
        try:
            parsed = validate(response.content)
            reads = _convert(parsed, task, task.hints or {})
        except SchemaError as exc:
            last_error = exc
            suffix = build_suffix(task, cfg) + " The previous reply failed validation: " + str(exc)[:_MAX_REPAIR_CHARS]
            continue
        return MeasureResult(
            callId=task.callId,
            reads=reads,
            usage=response.usage,
            errorCode=None,
        )
    return MeasureResult(callId=task.callId, reads=[], usage=None, errorCode=ErrorCode.E_VLM_SCHEMA)


def read_systems(
    tasks: list[MeasureTask],
    provider: VisionProvider,
    cfg: Config,
    emit=None,
) -> list[MeasureResult]:
    """按裁剪任务读小节；每个任务一次调用（裁切已经保证 ≤8 小节、≤1.6 MP）。"""
    if not tasks:
        return []
    workers = max(1, min(cfg.provider.max_concurrency, len(tasks)))

    def run(task: MeasureTask) -> MeasureResult:
        if emit is not None:
            emit("read", "read.call.started", callId=task.callId, system=task.system)
        result = _read_one(task, provider, cfg)
        if emit is not None:
            emit(
                "read",
                "read.call.finished",
                callId=task.callId,
                system=task.system,
                measures=len(result.reads),
                errorCode=result.errorCode.value if result.errorCode else None,
            )
        return result

    if workers == 1:
        return [run(task) for task in tasks]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, tasks))
