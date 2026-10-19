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


_MIDI_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def midi_name(value: int) -> str:
    """MIDI → 音名（60 = C4），写进提示词让人和模型都不歧义。"""
    return f"{_MIDI_NAMES[value % 12]}{value // 12 - 1}"


def key_display(key: str) -> str:
    """`BMajor` → `B 大调`，提示词里按乐理写法给。"""
    for suffix, mode in (("Major", "大调"), ("Minor", "小调")):
        if key.endswith(suffix):
            return f"{key[:-len(suffix)]} {mode}"
    return key


def build_suffix(task: MeasureTask, cfg: Config) -> str:
    """可变后缀：先说要读哪几个小节，再把骨架定死的参考参数写在后面。

    参考信息（拍号、调号、谱号、调弦、弦号）一律由骨架给出，读小节的模型只负责
    "按这些参数把图上的音符翻译出来"，不负责判定它们（§2.2 骨架的职责）。
    """
    hints = task.hints or {}
    indices = [box.index for box in task.measures]
    string_count = int(hints.get("stringCount", 4))
    tuning = hints.get("tuning") or []
    numbers = "、".join(str(index) for index in indices)
    lines = [f"请识别第 {numbers} 小节。", "参考信息（由骨架确定，直接采用，不要修改）："]

    if hints.get("clef"):
        lines.append(f"- 谱号：{hints['clef']}；书写音高 = 发声音高，没有八度移调")
    if hints.get("timeSignature"):
        lines.append(f"- 拍号：{hints['timeSignature']}")
    if hints.get("keySignature"):
        lines.append(f"- 调号：{key_display(hints['keySignature'])}")
    if len(tuning) == string_count:
        strings = "、".join(
            f"第 {index + 1} 弦 {midi_name(tuning[string_count - 1 - index])}"
            f"({tuning[string_count - 1 - index]})"
            for index in range(string_count)
        )
        lines.append(f"- 调弦（TAB 自上而下）：{strings}")
    else:
        lines.append(f"- TAB 有 {string_count} 条线")
    lines.append(f"- 弦号：TAB 顶线 = string 1，底线 = string {string_count}")
    if hints.get("hasStrip"):
        lines.append("- 左边那条窄条是谱号/调号引用，不属于本段内容")
    return "\n".join(lines)


def string_from_digit_y(
    digit_y: float,
    tab_lines: list[float],
    crop_box: list[float],
    string_count: int,
) -> int | None:
    """按品数数字的纵向位置定弦号（IR 约定：1 = 最低音弦）。

    TAB 弦线按 y 升序（第 0 条是最上面的线，对应最高音弦 = IR 的 string_count）。
    数字压在离它最近的那条线附近才算数：偏差超过半个弦间距就返回 None（交给上层）
    而不是硬猜（RD-06b）。
    """
    if not tab_lines or len(tab_lines) < 2:
        return None
    top, bottom = float(crop_box[1]), float(crop_box[3])
    page_y = top + float(digit_y) * (bottom - top)
    distances = [abs(page_y - float(line)) for line in tab_lines]
    nearest = min(range(len(distances)), key=lambda index: distances[index])
    gaps = [tab_lines[index + 1] - tab_lines[index] for index in range(len(tab_lines) - 1)]
    spacing = float(sum(gaps) / len(gaps))
    if spacing <= 0 or distances[nearest] >= 0.5 * spacing:
        return None
    ir_string = string_count - nearest
    return ir_string if 1 <= ir_string <= string_count else None


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
            reads.append(
                MeasureRead(
                    index=measure.index,
                    beats=[],
                    unreadable=True,
                    printed=measure.printed,
                    multiRest=measure.multiRest,
                )
            )
            continue
        beats: list[Beat] = []
        for beat in measure.beats:
            notes: list[Note] = []
            tab_lines = [float(line) for line in hints.get("tabLines") or []]
            crop_box = [float(value) for value in task.crop.box]
            for note in beat.notes:
                ir_string = string_count - note.string + 1
                if note.digitY is not None:
                    derived = string_from_digit_y(note.digitY, tab_lines, crop_box, string_count)
                    if derived is not None:
                        # 几何优先：数字压在哪个弦线上就是哪个弦（RD-06b）
                        ir_string = derived
                if not 1 <= ir_string <= string_count:
                    raise SchemaError(f"弦号越界：模型给 {note.string}，弦数 {string_count}")
                if len(tuning) == string_count:
                    # 权威音高由调弦 + 品数算（F-01）；模型的 pitch 只作为对账用。
                    pitch = tuning[ir_string - 1] + note.fret
                elif note.pitch is not None:
                    pitch = note.pitch
                else:
                    raise SchemaError("既没有调弦可算音高，模型也没有给 pitch")
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
        reads.append(
            MeasureRead(
                index=measure.index,
                beats=beats,
                unreadable=False,
                printed=measure.printed,
                multiRest=measure.multiRest,
            )
        )
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
