"""DeepSeek 接入的测试（规格 §2.3 V-02..V-06、§4.1；计划任务 6 的六个用例）。"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from aiaomr.kernel.errors import ErrorCode
from aiaomr.providers.base import ImageInput, ProviderCapabilities, ProviderError, VisionRequest
from aiaomr.providers.deepseek_flash import CAPS, DeepSeekClient, StubClient

BEIJING = timezone(timedelta(hours=8))
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = str(self._payload)

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def ok(content: str = '{"measures": []}', usage: dict | None = None) -> FakeResponse:
    return FakeResponse(
        200,
        {
            "choices": [{"message": {"content": content}}],
            "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def make_client(session: FakeSession, **kwargs) -> DeepSeekClient:
    kwargs.setdefault("sleep", lambda _s: None)
    return DeepSeekClient(CAPS, api_key="test-key", session=session, **kwargs)


def request(**kwargs) -> VisionRequest:
    payload = dict(
        call_id="c0001",
        prompt_prefix="Read the tab and reply with one json object.",
        prompt_suffix="Measures: 1-4.",
        images=(ImageInput(PNG, "image/png"),),
        max_tokens=1000,
        thinking=False,
    )
    payload.update(kwargs)
    return VisionRequest(**payload)


def test_images_only_in_user_messages() -> None:
    client = make_client(FakeSession([]))
    payload = client.build_request(request())

    messages = payload["messages"]
    assert len(messages) == 1 and messages[0]["role"] == "user"
    parts = messages[0]["content"]
    assert any(part["type"] == "image_url" for part in parts)
    assert all(part["type"] in ("text", "image_url") for part in parts)


def test_json_mode_and_prompt_mentions_json() -> None:
    client = make_client(FakeSession([]))
    payload = client.build_request(request())

    assert payload["response_format"] == {"type": "json_object"}
    text = payload["messages"][0]["content"][0]["text"]
    assert "json" in text

    with pytest.raises(ValueError):
        client.build_request(request(prompt_prefix="reply nicely"))


def test_empty_response_is_retried_then_raises_empty() -> None:
    session = FakeSession([ok(""), ok("  "), ok("")])
    client = make_client(session)

    with pytest.raises(ProviderError) as excinfo:
        client.read(request())

    assert excinfo.value.code is ErrorCode.E_VLM_EMPTY
    assert len(session.calls) == CAPS.retry_empty + 1


def test_401_is_not_retried() -> None:
    session = FakeSession([FakeResponse(401, {"error": "bad key"})])
    client = make_client(session)

    with pytest.raises(ProviderError) as excinfo:
        client.read(request())

    assert excinfo.value.code is ErrorCode.E_VLM_HTTP
    assert len(session.calls) == 1


def test_cost_is_decimal_with_four_places_off_peak() -> None:
    client = make_client(FakeSession([]))
    usage = {"prompt_tokens": 1000, "prompt_cache_miss_tokens": 1000,
             "prompt_cache_hit_tokens": 0, "completion_tokens": 900}

    assert client.cost_cny(usage) == Decimal("0.0046")
    assert client.cost_cny(usage, peak=True) == Decimal("0.0092")
    assert isinstance(client.cost_cny(usage), Decimal)


def test_capabilities_are_complete() -> None:
    for field_info in fields(ProviderCapabilities):
        value = getattr(CAPS, field_info.name)
        assert value is not None, field_info.name
    assert CAPS.name == "deepseek_flash"
    assert CAPS.model == "deepseek-flash"
    assert CAPS.supports_vision is True
    assert CAPS.max_concurrency > 0
    assert set(CAPS.pricing) == {"miss", "hit", "out"}


def test_peak_hours_are_beijing_weekday_windows() -> None:
    client = make_client(FakeSession([]))
    monday_morning = datetime(2026, 10, 19, 10, 0, tzinfo=BEIJING)  # 周一
    monday_lunch = datetime(2026, 10, 19, 12, 30, tzinfo=BEIJING)
    saturday = datetime(2026, 10, 17, 10, 0, tzinfo=BEIJING)

    assert client.is_peak(monday_morning) is True
    assert client.is_peak(monday_lunch) is False
    assert client.is_peak(saturday) is False


def test_429_is_retried_then_succeeds() -> None:
    session = FakeSession([FakeResponse(429, headers={"Retry-After": "0"}), ok()])
    client = make_client(session)

    response = client.read(request())

    assert response.content == '{"measures": []}'
    assert response.retry_count == 1
    assert len(session.calls) == 2


def test_stub_replays_recorded_response(tmp_path: Path) -> None:
    fixture = tmp_path / "c0001.resp.json"
    fixture.write_text('{"content": "{\\"measures\\": []}", "usage": {}, "raw": {}}', encoding="utf-8")
    stub = StubClient(CAPS, tmp_path)

    response = stub.read(request())
    assert response.content == '{"measures": []}'

    with pytest.raises(ProviderError):
        stub.read(request(call_id="missing"))
