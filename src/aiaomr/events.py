"""事件流：事件对象、NDJSON 写出、human 渲染。

这个模块只做三件事：把一条事件变成一行 JSON、把这条 JSON 写出去并立刻刷缓冲、
把事件渲染成终端上的一行人话。它没有业务判断，只依赖标准库（AGENTS.md 与 §10）。

用法上两条流是分开的（§10.2）：

- ndjson 模式：``Emitter(sink.stream).emit(...)`` 写 NDJSON；
- human 模式：``HumanRenderer().render(event)`` 得到一行文字，再写到 ``sink.stream``；
- 文件（``out/<song>/events.ndjson``，§8）永远只写 NDJSON 行。

时间戳一律 UTC、带毫秒、以 ``Z`` 结尾（§10.3）。
"""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO

__all__ = ["EVENT_VERSION", "STAGES", "LEVELS", "Event", "Emitter", "HumanRenderer", "Sink", "open_sink"]

#: 事件 schema 版本（§10.3）。破坏性变更必须升这个数。
EVENT_VERSION = 1

#: ``stage`` 的合法取值（§10.3）。这里只登记，不在写出时强制校验，免得 GUI 回放旧事件时崩溃。
STAGES = frozenset(
    {
        "ingest",
        "locate",
        "skeleton",
        "read",
        "verify",
        "adjudicate",
        "assemble",
        "build",
        "audit",
        "eval",
        "run",
    }
)

#: ``level`` 的合法取值（§10.3）。
LEVELS = frozenset({"debug", "info", "warn", "error"})

_FORMATS = ("auto", "ndjson", "human")

_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def utc_now() -> str:
    """返回 UTC 时间戳，带三位毫秒，例如 ``2026-10-17T23:40:00.123Z``。"""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _json_default(value: Any) -> Any:
    """事件数据里偶尔会有 Decimal（钱）和 Path，转成 JSON 能表达的标量。"""

    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"事件数据不能序列化为 JSON：{type(value).__name__}")


@dataclass(frozen=True)
class Event:
    """一条事件，字段顺序照 §10.3。"""

    v: int
    seq: int
    ts: str
    level: str
    stage: str
    event: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": self.v,
            "seq": self.seq,
            "ts": self.ts,
            "level": self.level,
            "stage": self.stage,
            "event": self.event,
            "data": self.data,
        }

    def to_json(self) -> str:
        """一行 JSON，不包含换行符；中文原样输出（ensure_ascii=False）。"""

        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        )


class Emitter:
    """把事件写成 NDJSON：一行一个，写完立刻 flush（§10.2、§10.3）。"""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._seq = 0
        self._lock = threading.Lock()

    @property
    def seq(self) -> int:
        """最后一条已写出事件的序号；还没写过时为 0。"""

        return self._seq

    def emit(self, stage_name: str, event_name: str, level: str = "info", **data: Any) -> Event:
        """写出一条事件。额外关键字参数全部进 ``data``。

        参数名刻意不叫 `stage`/`event`：`data` 里本来就有同名的业务字段
        （例如 `stage.started` 的 `data.stage`），重名会让调用方没法传。
        """

        with self._lock:
            self._seq += 1
            record = Event(
                v=EVENT_VERSION,
                seq=self._seq,
                ts=utc_now(),
                level=level,
                stage=stage_name,
                event=event_name,
                data=dict(data),
            )
            self._stream.write(record.to_json() + "\n")
            self._stream.flush()
            return record


@dataclass
class Sink:
    """事件的输出落点：一条文本流，加上解析后的格式。"""

    stream: TextIO
    fmt: str
    owns_stream: bool = False

    @property
    def is_human(self) -> bool:
        return self.fmt == "human"

    def write_line(self, line: str) -> None:
        """写一行并立刻 flush。行里不允许带换行符。"""

        if "\n" in line or "\r" in line:
            raise ValueError("事件行里不许带换行符")
        self.stream.write(line + "\n")
        self.stream.flush()

    def close(self) -> None:
        """只关闭自己打开的文件，不关 stdout。"""

        if self.owns_stream and not self.stream.closed:
            self.stream.close()

    def __enter__(self) -> "Sink":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()


def _is_tty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        return False


def open_sink(path: str | Path | None = None, fmt: str = "auto") -> Sink:
    """按 §10.2 打开事件落点。

    - 给了 ``path``：写文件，格式一律是 ``ndjson``（文件里不许出现 human 行）；
    - 没给 ``path``：写 stdout，``auto`` 时 TTY 选 ``human``，否则选 ``ndjson``。
    """

    if fmt not in _FORMATS:
        raise ValueError(f"未知的输出格式：{fmt!r}，只支持 {', '.join(_FORMATS)}")

    if path is not None:
        handle = open(path, "w", encoding="utf-8", newline="\n")
        return Sink(stream=handle, fmt="ndjson", owns_stream=True)

    stream = sys.stdout
    if fmt == "auto":
        fmt = "human" if _is_tty(stream) else "ndjson"
    return Sink(stream=stream, fmt=fmt, owns_stream=False)


def _field(event: Any, name: str, default: Any = None) -> Any:
    """Event 或回放出来的 dict 都能读。"""

    if isinstance(event, Mapping):
        return event.get(name, default)
    return getattr(event, name, default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(value: Any) -> str:
    return f"{_float(value):.4f}"


def _seconds(duration_ms: Any) -> str | None:
    if duration_ms is None:
        return None
    try:
        return f"{float(duration_ms) / 1000:.1f}s"
    except (TypeError, ValueError):
        return None


def _summary(stage: str, detail: str, duration_ms: Any = None) -> str:
    """一根阶段摘要行，形状照 §10.6。"""

    line = f"{stage:<12}▸ {detail}"
    seconds = _seconds(duration_ms)
    if seconds is None:
        return line
    if len(line) < 61:
        line = f"{line:<61}"
    else:
        line += "  "
    return line + f"{seconds:>5}"


def _time_signature(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return f"{value[0]}/{value[1]}"
    if isinstance(value, Mapping):
        beats = value.get("beats", value.get("numerator"))
        beat_type = value.get("beatType", value.get("denominator"))
        if beats is not None and beat_type is not None:
            return f"{beats}/{beat_type}"
    return None


def _tuning_names(tuning: Any) -> str:
    """MIDI 音高转成音名（低→高），例如 ``[28, 33, 38, 43]`` → ``EADG``。"""

    if not isinstance(tuning, (list, tuple)):
        return ""
    names: list[str] = []
    for value in tuning:
        if isinstance(value, str):
            names.append(value)
        elif isinstance(value, int) and not isinstance(value, bool):
            names.append(_NOTE_NAMES[value % 12] if 0 <= value <= 127 else str(value))
    return "".join(names)


def _by_rule(by_rule: Any) -> str:
    """``{"A1": 4, "A8": 3}`` → ``"A1×4, A8×3"``，按规则编号排序。"""

    if not isinstance(by_rule, Mapping) or not by_rule:
        return ""

    def sort_key(item: tuple[Any, Any]) -> tuple[int, str]:
        name = str(item[0])
        digits = "".join(ch for ch in name if ch.isdigit())
        return (int(digits) if digits else 10**6, name)

    return ", ".join(
        f"{name}×{_int(count)}" for name, count in sorted(by_rule.items(), key=sort_key)
    )


def _with_trailing_slash(path: Any) -> str:
    text = str(path)
    return text.rstrip("/\\") + "/"


class HumanRenderer:
    """把事件渲染成终端上的一行文字（§10.6）。

    认识的事件返回一行 ``str``；不认识、或者 human 模式不打印的事件返回 ``None``。
    渲染器不抛异常：GUI 回放旧事件时字段可能缺失（§10.3）。
    """

    def __init__(self) -> None:
        self._out_dir: str | None = None
        self._handlers = {
            "run.started": self._render_run_started,
            "run.finished": self._render_run_finished,
            "locate.done": self._render_locate_done,
            "skeleton.done": self._render_skeleton_done,
            "read.done": self._render_read_done,
            "verify.done": self._render_verify_done,
            "adjudicate.done": self._render_adjudicate_done,
            "build.validate": self._render_build_validate,
            "build.written": self._render_build_written,
            "build.failed": self._render_build_failed,
            "audit.result": self._render_audit_result,
            "metrics.summary": self._render_metrics_summary,
        }

    def render(self, event: Any) -> str | None:
        name = _field(event, "event")
        if not isinstance(name, str) or not name:
            return None
        handler = self._handlers.get(name)
        if handler is None:
            return None

        raw_data = _field(event, "data", {})
        data = raw_data if isinstance(raw_data, Mapping) else {}
        stage = str(_field(event, "stage", "") or "")
        return handler(stage, data)

    # -- run 级 ---------------------------------------------------------

    def _render_run_started(
        self, stage: str, data: Mapping[str, Any]
    ) -> str | None:
        # human 模式不打印启动行，但记下产物目录，失败块里要用。
        out_dir = data.get("outDir")
        if out_dir:
            self._out_dir = str(out_dir)
        return None

    def _render_run_finished(self, stage: str, data: Mapping[str, Any]) -> str | None:
        status = data.get("status")
        if status == "ok":
            gp5 = data.get("gp5")
            return f"✓ {gp5}" if gp5 else None

        block = data.get("block")
        block = block if isinstance(block, Mapping) else None
        if block is not None:
            head = f"✗ 阻断于 {block.get('stage', '?')}"
        elif status == "aborted":
            head = "✗ 运行被中断"
        elif status:
            head = f"✗ 运行结束（{status}）"
        else:
            return None

        parts = [head]
        spent = data.get("spentCny", data.get("cny"))
        if spent is not None:
            parts.append(f"已花费 ¥{_money(spent)}")
        out_dir = data.get("outDir", self._out_dir)
        if out_dir:
            parts.append(f"产物保留在 {_with_trailing_slash(out_dir)}")
        if data.get("resumable", True):
            parts.append("可 --resume")
        return " · ".join(parts)

    # -- 阶段摘要 -------------------------------------------------------

    def _render_locate_done(self, stage: str, data: Mapping[str, Any]) -> str:
        detail = f"{_int(data.get('systems'))} systems, {_int(data.get('measures'))} measures"
        return _summary(stage, detail, data.get("durationMs"))

    def _render_skeleton_done(self, stage: str, data: Mapping[str, Any]) -> str | None:
        parts: list[str] = []
        key = data.get("key", data.get("keySignature"))
        if key:
            parts.append(str(key))
        signature = _time_signature(data.get("timeSignature", data.get("timeSignatures")))
        if signature:
            parts.append(signature)
        tempo = data.get("tempo")
        if tempo is not None:
            parts.append(f"♩={tempo}")
        tuning = _tuning_names(data.get("tuning"))
        string_count = data.get("stringCount", len(tuning) if tuning else None)
        if tuning and string_count is not None:
            parts.append(f"{string_count}-string {tuning}")
        if not parts:
            return None
        return _summary(stage, ", ".join(parts), data.get("durationMs"))

    def _render_read_done(self, stage: str, data: Mapping[str, Any]) -> str:
        systems = _int(data.get("systems"))
        done = _int(data.get("systemsDone"), systems)
        detail = (
            f"{done}/{systems} systems, "
            f"{_int(data.get('calls'))} calls, "
            f"{_int(data.get('emptyReturns'))} empty returns"
        )
        return _summary(stage, detail, data.get("durationMs"))

    def _render_verify_done(self, stage: str, data: Mapping[str, Any]) -> str:
        detail = f"{_int(data.get('alarms'))} alarms"
        rules = _by_rule(data.get("byRule"))
        if rules:
            detail += f" ({rules})"
        return _summary(stage, detail, data.get("durationMs"))

    def _render_adjudicate_done(
        self, stage: str, data: Mapping[str, Any]
    ) -> str | None:
        # §10.4 把 adjudicate.done 写成逐条终裁；§10.6 的阶段行却是聚合结果，两种都认。
        if "resolved" in data or "alarmsResolved" in data:
            resolved = _int(data.get("resolved", data.get("alarmsResolved")))
            total = _int(data.get("total", data.get("alarms")), resolved)
            detail = f"{resolved}/{total} resolved"
            overrode = data.get("overrode")
            if isinstance(overrode, Mapping):
                counts = [
                    f"{name} {_int(count)}" for name, count in overrode.items() if _int(count)
                ]
                if counts:
                    detail += f"  (overrode {', '.join(counts)})"
            return _summary(stage, detail, data.get("durationMs"))

        alarm_id = data.get("alarmId")
        if alarm_id:
            detail = f"{alarm_id} → {data.get('final', '?')}"
            reason = data.get("reason")
            if reason:
                detail += f"（{reason}）"
            return _summary(stage, detail, data.get("durationMs"))
        return None

    # -- build / audit --------------------------------------------------

    def _render_build_validate(self, stage: str, data: Mapping[str, Any]) -> str | None:
        if "ok" not in data:
            return None
        ok = bool(data.get("ok"))
        errors = data.get("errors")
        detail = "validate OK" if ok else "validate FAIL"
        if not ok and isinstance(errors, (list, tuple)):
            detail += f" ({len(errors)} errors)"
        return _summary(stage, detail)

    def _render_build_written(self, stage: str, data: Mapping[str, Any]) -> str | None:
        roundtrip = data.get("roundtrip")
        if not roundtrip:
            return None
        return _summary(stage, f"ROUND-TRIP {roundtrip}")

    def _render_build_failed(self, stage: str, data: Mapping[str, Any]) -> str | None:
        error = data.get("error")
        if not error:
            return None
        detail = f"✗ {error}"
        if data.get("detail"):
            detail += f"  {data['detail']}"
        return _summary(stage, detail)

    def _render_audit_result(self, stage: str, data: Mapping[str, Any]) -> str | None:
        if data.get("skipped"):
            return _summary(stage, "skipped")
        if "pitchMismatch" not in data and "barErrors" not in data:
            return None
        detail = f"{_int(data.get('pitchMismatch'))}/{_int(data.get('barErrors'))}"
        return _summary(stage, detail)

    # -- 最终块 ---------------------------------------------------------

    def _render_metrics_summary(
        self, stage: str, data: Mapping[str, Any]
    ) -> str | None:
        if "cny" not in data and "seconds" not in data:
            return None
        line = "  cost"
        if "cny" in data:
            line += f" ¥{_money(data.get('cny'))}"
        if data.get("cnyPer8") is not None:
            line += f" (¥{_money(data.get('cnyPer8'))} per 8 measures)"
        if data.get("seconds") is not None:
            line += f" · {_float(data.get('seconds')):.1f} s"
        return line
