"""命令行的测试（规格 §2.10、§7.1、§10；计划任务 13 的四个用例）。全部走离线回放。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from aiaomr.cli import main
from tests.fixtures.pages import one_system_page


def make_page(tmp_path: Path) -> Path:
    arr, _bands = one_system_page(width=1600, height=420, deg=12, bars=(60, 500, 940))
    path = tmp_path / "page.png"
    Image.fromarray(arr).convert("RGB").save(path)
    return path


def read_content(measures: int = 2) -> dict:
    payload = []
    for index in range(1, measures + 1):
        beats = [
            {"duration": "quarter", "dots": 0, "rest": False,
             "notes": [{"string": 1, "fret": 3, "pitch": 46, "digit": "3"}]}
            for _ in range(4)
        ]
        payload.append({"index": index, "beats": beats})
    return {"measures": payload}


def write_fixtures(out_dir: Path, title: str = "测试曲") -> None:
    calls = out_dir / "calls"
    calls.mkdir(parents=True, exist_ok=True)
    skeleton = {
        "timeSignature": {"beats": 4, "beatType": 4},
        "keySignature": "CMajor",
        "tempo": 96,
        "tuning": [28, 33, 38, 43],
        "stringCount": 4,
        "title": title,
        "artist": "测试作者",
    }
    (calls / "skeleton.resp.json").write_text(
        json.dumps({"content": json.dumps(skeleton, ensure_ascii=False), "usage": {}, "raw": {}},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    (calls / "01s01p01.resp.json").write_text(
        json.dumps({"content": json.dumps(read_content(2)), "usage": {}, "raw": {}},
                   ensure_ascii=False),
        encoding="utf-8",
    )


def run_cli(tmp_path: Path, page: Path, *extra: str, song: str = "测试曲"):
    out_dir = tmp_path / "out"
    code = main(["run", "--input", str(page), "--provider", "stub", "--out", str(out_dir),
                 "--format", "ndjson", "--song", song, *extra])
    return code, out_dir


def read_events(out_dir: Path) -> list[dict]:
    return [json.loads(line) for line in (out_dir / "events.ndjson").read_text(
        encoding="utf-8").splitlines() if line.strip()]


def test_full_run_writes_gp5_and_valid_events(tmp_path: Path) -> None:
    page = make_page(tmp_path)
    out_dir = tmp_path / "out"
    write_fixtures(out_dir)

    code, out_dir = run_cli(tmp_path, page)

    assert code == 0
    events = read_events(out_dir)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    finished = [event for event in events if event["event"] == "run.finished"]
    assert len(finished) == 1 and finished[0]["data"]["status"] == "ok"
    assert (out_dir / "测试曲.gp5").exists()
    assert (out_dir / "ir.json").exists()
    payload = json.loads((out_dir / "ir.json").read_text(encoding="utf-8"))
    assert payload["score"]["measureCount"] == 2


def test_resume_does_not_repeat_paid_calls(tmp_path: Path) -> None:
    page = make_page(tmp_path)
    out_dir = tmp_path / "out"
    write_fixtures(out_dir)

    assert run_cli(tmp_path, page)[0] == 0
    code, out_dir = run_cli(tmp_path, page, "--resume")

    assert code == 0
    events = read_events(out_dir)
    read_done = [event for event in events if event["event"] == "read.done"][-1]
    assert read_done["data"]["calls"] == 0
    assert read_done["data"]["cached"] >= 1


def test_write_validation_failure_blocks_with_exit_2(tmp_path: Path) -> None:
    page = make_page(tmp_path)
    out_dir = tmp_path / "out"
    write_fixtures(out_dir, title="吉他🎸")  # cp936 编不进去，写出前校验必须拒绝

    code, out_dir = run_cli(tmp_path, page)

    assert code == 2
    events = read_events(out_dir)
    block = [event for event in events if event["event"] == "block"][-1]
    assert block["data"]["code"] == "E_BUILD_VALIDATE"
    finished = [event for event in events if event["event"] == "run.finished"][-1]
    assert finished["data"]["status"] == "blocked" and finished["data"]["exitCode"] == 2
    assert not (out_dir / "测试曲.gp5").exists()
    # 之前的中间产物必须保留
    assert (out_dir / "pageset.json").exists()
    assert (out_dir / "skeleton.json").exists()


def test_interrupt_returns_130(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page = make_page(tmp_path)
    out_dir = tmp_path / "out"
    write_fixtures(out_dir)
    monkeypatch.setenv("AIAOMR_TEST_STUB_INTERRUPT_AFTER", "1")

    code, out_dir = run_cli(tmp_path, page)

    assert code == 130
    events = read_events(out_dir)
    finished = [event for event in events if event["event"] == "run.finished"][-1]
    assert finished["data"]["status"] == "interrupted"


def test_until_stage_stops_early(tmp_path: Path) -> None:
    page = make_page(tmp_path)
    out_dir = tmp_path / "out"
    write_fixtures(out_dir)

    code, out_dir = run_cli(tmp_path, page, "--until", "locate")

    assert code == 0
    events = read_events(out_dir)
    finished = [event for event in events if event["event"] == "run.finished"][-1]
    assert finished["data"]["status"] == "stopped"
    assert not (out_dir / "测试曲.gp5").exists()


def test_staff_stage_writes_rhythm_and_events(tmp_path: Path) -> None:
    """`--until staff` 必须跑完读谱阶段：产物落盘、事件按小节发、不联网（约定见 spec-staff §12.4）。"""
    page = make_page(tmp_path)
    out_dir = tmp_path / "out"
    write_fixtures(out_dir)

    code, out_dir = run_cli(tmp_path, page, "--until", "staff")

    assert code == 0
    rhythm_path = out_dir / "staff" / "rhythm.json"
    assert rhythm_path.exists()
    payload = json.loads(rhythm_path.read_text(encoding="utf-8"))
    events = read_events(out_dir)
    per_measure = [event for event in events if event["event"] == "staff.measure"]
    assert len(per_measure) == len(payload["measures"])
    done = [event for event in events if event["event"] == "staff.done"][-1]
    assert done["data"]["measures"] == len(payload["measures"])
    finished = [event for event in events if event["event"] == "run.finished"][-1]
    assert finished["data"]["status"] == "stopped"
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    # 读谱阶段不调模型：没有任何 read.* 事件。
    assert not [event for event in events if event["event"].startswith("read.")]
