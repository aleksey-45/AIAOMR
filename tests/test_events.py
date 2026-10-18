"""事件流的单元测试。

覆盖规格 §10.2（两条流）、§10.3（事件通用结构）、§10.5（progress 不节流）、
§10.6（human 模式的样子）以及 §8 的 events.ndjson 落盘要求。
"""

from __future__ import annotations

import io
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from aiaomr.events import Emitter, Event, HumanRenderer, open_sink

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class RecordingStream:
    """记下每次 write/flush 的顺序，用来断言"写完一行立刻刷缓冲"。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.flushes = 0

    def write(self, text: str) -> int:
        self.calls.append(("write", text))
        return len(text)

    def flush(self) -> None:
        self.flushes += 1
        self.calls.append(("flush", None))


class FakeStdout(io.StringIO):
    """可控的 isatty()，用来测 --format auto 的选择。"""

    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _event(stage: str, name: str, data: dict | None = None) -> Event:
    return Event(
        v=1,
        seq=1,
        ts="2026-10-17T23:40:00.123Z",
        level="info",
        stage=stage,
        event=name,
        data={} if data is None else data,
    )


def test_seq_starts_at_one_and_increments():
    stream = io.StringIO()
    emitter = Emitter(stream)

    for done in (1, 2, 3):
        emitter.emit("read", "progress", done=done, total=3, unit="systems")

    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [event["seq"] for event in events] == [1, 2, 3]
    assert [event["v"] for event in events] == [1, 1, 1]
    assert events[0]["level"] == "info"
    assert events[0]["stage"] == "read"
    assert events[0]["event"] == "progress"
    assert events[0]["data"] == {"done": 1, "total": 3, "unit": "systems"}
    assert set(events[0]) == {"v", "seq", "ts", "level", "stage", "event", "data"}


def test_each_event_is_exactly_one_line_of_parseable_json():
    stream = io.StringIO()
    emitter = Emitter(stream)

    emitter.emit(
        "ingest",
        "input.registered",
        file="打上花火/1.png",
        sha256="a" * 64,
        width=1200,
        height=1700,
        mp=2.04,
    )
    emitter.emit("run", "run.started", input="打上花火/1.png", song="打上花火")

    text = stream.getvalue()
    lines = text.splitlines()
    assert len(lines) == 2
    assert text.endswith("\n")
    for line in lines:
        assert json.loads(line)["v"] == 1
    # ensure_ascii=False：中文原样写出，不变成 \uXXXX。
    assert "打上花火" in text
    assert "\\u" not in text


def test_every_line_is_flushed_immediately():
    stream = RecordingStream()
    emitter = Emitter(stream)

    emitter.emit("run", "run.started", song="打上花火")
    emitter.emit("run", "run.finished", status="ok", exitCode=0)

    assert stream.flushes == 2
    # 每行都是"写一次、刷一次"，不允许攒到最后。
    assert [kind for kind, _ in stream.calls] == ["write", "flush", "write", "flush"]
    for kind, text in stream.calls:
        if kind == "write":
            assert text is not None and text.endswith("\n")


def test_timestamp_is_utc_with_milliseconds():
    stream = io.StringIO()
    event = Emitter(stream).emit("run", "run.started")

    assert TIMESTAMP_RE.fullmatch(event.ts)
    parsed = datetime.strptime(event.ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )
    assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 5


def test_level_can_be_overridden():
    stream = io.StringIO()
    event = Emitter(stream).emit(
        "build", "build.failed", level="error", error="E_BUILD_VALIDATE", detail="m57"
    )

    assert event.level == "error"
    assert json.loads(stream.getvalue())["level"] == "error"


def test_concurrent_emits_keep_seq_contiguous():
    stream = io.StringIO()
    emitter = Emitter(stream)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: emitter.emit("read", "progress", done=i), range(50)))

    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(events) == 50
    assert sorted(event["seq"] for event in events) == list(range(1, 51))


@pytest.mark.parametrize(
    ("stage", "name", "data"),
    [
        ("locate", "locate.done", {"systems": 18, "measures": 107, "durationMs": 1200}),
        (
            "skeleton",
            "skeleton.done",
            {
                "title": "打上花火",
                "artist": "DAOKO",
                "tempo": 96,
                "tuning": [28, 33, 38, 43],
                "stringCount": 4,
                "timeSignature": "4/4",
                "measureCount": 107,
                "defaulted": [],
            },
        ),
        (
            "read",
            "read.done",
            {
                "systems": 18,
                "measures": 107,
                "calls": 21,
                "emptyReturns": 0,
                "cny": 0.112,
                "durationMs": 11400,
            },
        ),
        (
            "verify",
            "verify.done",
            {"alarms": 9, "byRule": {"A1": 4, "A8": 3, "A9": 2}, "durationMs": 800},
        ),
        (
            "adjudicate",
            "adjudicate.done",
            {
                "resolved": 9,
                "total": 9,
                "overrode": {"read": 3, "locate": 1},
                "durationMs": 4800,
            },
        ),
        (
            "adjudicate",
            "adjudicate.done",
            {"alarmId": "A1-m57", "final": "keep", "reason": "reread", "overrode": "read"},
        ),
        ("build", "build.validate", {"ok": True, "errors": []}),
        (
            "build",
            "build.written",
            {"path": "out/打上花火/打上花火.gp5", "bytes": 1234, "roundtrip": "OK"},
        ),
        ("build", "build.failed", {"error": "E_BUILD_VALIDATE", "detail": "m57 ticks"}),
        ("audit", "audit.result", {"pitchMismatch": 0, "barErrors": 0}),
        (
            "run",
            "run.finished",
            {
                "status": "ok",
                "exitCode": 0,
                "gp5": "out/打上花火/打上花火.gp5",
                "seconds": 14.2,
                "cny": 0.112,
                "artifacts": ["out/打上花火/打上花火.gp5"],
            },
        ),
        (
            "run",
            "metrics.summary",
            {
                "systems": 18,
                "measures": 107,
                "calls": 21,
                "retries": 0,
                "emptyReturns": 0,
                "cny": 0.112,
                "cnyPer8": 0.0087,
                "seconds": 14.2,
                "alarms": 9,
                "alarmsResolved": 9,
                "degradations": [],
            },
        ),
    ],
)
def test_known_events_render_one_line(stage, name, data):
    line = HumanRenderer().render(_event(stage, name, data))

    assert isinstance(line, str)
    assert line
    assert "\n" not in line and "\r" not in line


def test_run_finished_failure_renders_block_summary():
    renderer = HumanRenderer()
    renderer.render(_event("run", "run.started", {"outDir": "out/打上花火"}))
    line = renderer.render(
        _event(
            "run",
            "run.finished",
            {
                "status": "failed",
                "exitCode": 1,
                "seconds": 14.2,
                "spentCny": 0.0721,
                "spentCnyPer8": 0.0054,
                "resumable": True,
                "block": {
                    "stage": "build",
                    "error": "E_BUILD_VALIDATE",
                    "reason": "m57 ticks 4020 ≠ 3840",
                    "location": "m57",
                    "suggestions": ["重读 m56-58"],
                },
            },
        )
    )

    assert isinstance(line, str)
    assert "\n" not in line
    assert "阻断于 build" in line
    assert "¥0.0721" in line
    assert "可 --resume" in line


@pytest.mark.parametrize(
    "name", ["gui.unknown", "read.call.started", "progress", "alarm.raised"]
)
def test_unknown_or_unrendered_events_return_none(name):
    assert HumanRenderer().render(_event("read", name, {"done": 1})) is None


def test_renderer_accepts_replayed_dict():
    """GUI 回放 events.ndjson 时拿到的是 dict，不是 Event。"""

    replayed = {
        "v": 1,
        "seq": 4,
        "ts": "2026-10-17T23:40:00.123Z",
        "level": "info",
        "stage": "locate",
        "event": "locate.done",
        "data": {"systems": 18, "measures": 107, "durationMs": 1200},
    }

    line = HumanRenderer().render(replayed)

    assert isinstance(line, str)
    assert "18" in line and "107" in line


def test_known_event_with_empty_data_does_not_crash():
    renderer = HumanRenderer()
    for name in ("locate.done", "skeleton.done", "read.done", "verify.done", "build.written"):
        line = renderer.render(_event("x", name, {}))
        assert line is None or isinstance(line, str)


def test_file_sink_writes_ndjson_even_when_human_is_requested(tmp_path):
    path = tmp_path / "events.ndjson"
    sink = open_sink(path, "human")
    try:
        # §10.2：文件里只写 NDJSON 行，human 渲染只用于终端。
        assert sink.fmt == "ndjson"
        Emitter(sink.stream).emit("run", "run.started", song="打上花火")
    finally:
        sink.close()

    raw = path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert len(raw.splitlines()) == 1
    assert json.loads(raw)["data"]["song"] == "打上花火"
    assert sink.stream.closed


def test_file_sink_auto_also_resolves_to_ndjson(tmp_path):
    sink = open_sink(tmp_path / "events.ndjson", "auto")
    try:
        assert sink.fmt == "ndjson"
    finally:
        sink.close()


def test_auto_format_follows_tty(monkeypatch):
    tty = FakeStdout(tty=True)
    monkeypatch.setattr(sys, "stdout", tty)
    assert open_sink(None, "auto").fmt == "human"

    plain = FakeStdout(tty=False)
    monkeypatch.setattr(sys, "stdout", plain)
    assert open_sink(None, "auto").fmt == "ndjson"


def test_stdout_sink_honours_explicit_format(monkeypatch):
    fake = FakeStdout(tty=True)
    monkeypatch.setattr(sys, "stdout", fake)

    sink = open_sink(None, "ndjson")

    assert sink.fmt == "ndjson"
    assert sink.stream is fake


def test_stdout_sink_is_not_closed(monkeypatch):
    fake = FakeStdout(tty=False)
    monkeypatch.setattr(sys, "stdout", fake)

    sink = open_sink(None, "ndjson")
    sink.close()

    assert not fake.closed


def test_unknown_format_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        open_sink(tmp_path / "events.ndjson", "xml")
