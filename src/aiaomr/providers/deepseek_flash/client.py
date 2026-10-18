"""DeepSeek V4.1-Flash 的调用实现（规格 §4.1、§2.3 V-02..V-06、V-08）。

三件事在这里做：

- 拼请求：图片只能放在 **user** 消息里，必须开 JSON 模式；
- 重试：空返回重试 `fake` 次，429/5xx/超时退避重试，401/403 一次都不重试；
- 记账：按 `usage` 算人民币，谷价口径（峰价另算）。

真实网络请求只允许发生在这一层，其余层通过 `VisionProvider.read` 拿结果。
"""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import requests

from ...kernel.errors import ErrorCode
from ..base import (
    ImageInput,
    ProviderCapabilities,
    ProviderError,
    VisionRequest,
    VisionResponse,
)

_ENDPOINT = "https://api.deepseek.com/chat/completions"
_TIMEOUT_S = 300
_BEIJING = timezone(timedelta(hours=8))
# 修复提示只许带截断后的错误摘要（V-05b）：最多 500 个字符。
_MAX_REPAIR_CHARS = 500


class DeepSeekClient:
    """`deepseek_flash` 的实现；`session` 可注入，测试里用假对象，不发网络。"""

    def __init__(
        self,
        caps: ProviderCapabilities,
        api_key: str | None = None,
        base_url: str = _ENDPOINT,
        session: object | None = None,
        sleep=time.sleep,
        record_dir: str | Path | None = None,
        now=None,
    ) -> None:
        self.caps = caps
        self._api_key = api_key
        self._base_url = base_url
        self._session = session or requests.Session()
        self._sleep = sleep
        self._record_dir = Path(record_dir) if record_dir else None
        self._now = now or (lambda: datetime.now(_BEIJING))

    # ---- 请求构造 -----------------------------------------------------
    def build_request(self, request: VisionRequest) -> dict:
        text = request.prompt_prefix + request.prompt_suffix
        if not self.caps.supports_json_mode:
            raise ValueError("该 provider 不支持 JSON 模式")
        if "json" not in text:
            raise ValueError('prompt 里必须出现字面量 "json"（V-03）')
        if len(request.images) > self.caps.max_images_per_request:
            raise ValueError(
                f"单次请求图片数 {len(request.images)} 超过上限 {self.caps.max_images_per_request}（V-04）"
            )
        content: list[dict] = [{"type": "text", "text": text}]
        for image in request.images:
            if len(image.data) > self.caps.max_image_bytes:
                raise ValueError("单图超过 caps.max_image_bytes（V-04）")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": _data_url(image),
                        "detail": "original",
                    },
                }
            )
        payload: dict = {
            "model": self.caps.model,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "max_tokens": request.max_tokens,
        }
        if self.caps.supports_thinking_toggle:
            payload["thinking"] = {"type": "enabled" if request.thinking else "disabled"}
        return payload

    # ---- 调用与重试 ---------------------------------------------------
    def read(self, request: VisionRequest) -> VisionResponse:
        key = self._api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            raise ProviderError(ErrorCode.E_VLM_HTTP, "缺少 DEEPSEEK_API_KEY")
        payload = self.build_request(request)
        retry_empty_left = self.caps.retry_empty
        retry_http_left = self.caps.retry_http
        retries = 0
        repair_note = ""
        started = time.monotonic()

        while True:
            if repair_note:
                payload = self._with_repair(payload, repair_note)
            try:
                response = self._session.post(
                    self._base_url,
                    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=_TIMEOUT_S,
                )
            except requests.RequestException as exc:  # 网络层失败按 5xx 对待
                if retry_http_left <= 0:
                    raise ProviderError(ErrorCode.E_VLM_HTTP, f"网络错误：{exc!r}") from exc
                retry_http_left -= 1
                retries += 1
                self._sleep(_backoff_http(retries))
                continue

            status = int(getattr(response, "status_code", 0))
            if status == 200:
                data = response.json()
                content = _content_of(data)
                if content.strip():
                    response_obj = VisionResponse(
                        content=content,
                        usage=data.get("usage", {}),
                        duration_ms=int((time.monotonic() - started) * 1000),
                        retry_count=retries,
                        raw=data,
                    )
                    self._record(request, payload, data)
                    return response_obj
                if retry_empty_left <= 0:
                    raise ProviderError(ErrorCode.E_VLM_EMPTY, "重试后仍然返回空内容（V-05）")
                retry_empty_left -= 1
                retries += 1
                repair_note = "上一次回复是空的。只输出一个 json 对象，不要输出别的。"
                self._sleep(_backoff_empty(retries))
                continue

            if status in (401, 403):
                raise ProviderError(ErrorCode.E_VLM_HTTP, f"鉴权失败 HTTP {status}，禁止重试（V-06）")
            if status == 429 or status >= 500:
                if retry_http_left <= 0:
                    raise ProviderError(ErrorCode.E_VLM_HTTP, f"HTTP {status}，重试次数用尽（V-06）")
                retry_http_left -= 1
                retries += 1
                self._sleep(_retry_after(response, _backoff_http(retries)))
                continue
            raise ProviderError(ErrorCode.E_VLM_HTTP, f"HTTP {status}：{_short(response)}")

    # ---- 记账 ---------------------------------------------------------
    def cost_cny(self, usage: dict, peak: bool = False) -> Decimal:
        """按用量算人民币，四位小数。默认按谷价，`peak=True` 按峰价（§2.3.2）。"""
        rates = self.caps.peak_pricing if peak else self.caps.pricing
        hit = int(usage.get("prompt_cache_hit_tokens", 0))
        prompt = int(usage.get("prompt_tokens", 0))
        miss = int(usage.get("prompt_cache_miss_tokens", max(0, prompt - hit)))
        out = int(usage.get("completion_tokens", 0))
        total = (
            Decimal(miss) * Decimal(str(rates["miss"]))
            + Decimal(hit) * Decimal(str(rates["hit"]))
            + Decimal(out) * Decimal(str(rates["out"]))
        ) / Decimal(1_000_000)
        return total.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    def is_peak(self, moment: datetime | None = None) -> bool:
        moment = moment or self._now()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=_BEIJING)
        moment = moment.astimezone(_BEIJING)
        if moment.weekday() >= 5:
            return False
        minutes = moment.hour * 60 + moment.minute
        return (9 * 60 <= minutes < 12 * 60) or (14 * 60 <= minutes < 18 * 60)

    # ---- 内部 ---------------------------------------------------------
    def _with_repair(self, payload: dict, note: str) -> dict:
        """把修复提示追加到 user 消息末尾；前缀保持不动（V-11、V-05b）。"""
        repaired = json.loads(json.dumps(payload))
        content = repaired["messages"][0]["content"]
        content.append({"type": "text", "text": note[:_MAX_REPAIR_CHARS]})
        return repaired

    def _record(self, request: VisionRequest, payload: dict, data: dict) -> None:
        if self._record_dir is None:
            return
        self._record_dir.mkdir(parents=True, exist_ok=True)
        for suffix, body in (("req", {"promptVersion": "p0", "payload": payload}),
                             ("resp", {"usage": data.get("usage", {}), "raw": data})):
            target = self._record_dir / f"{request.call_id}.{suffix}.json"
            temporary = target.with_name(target.name + ".tmp")
            temporary.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
            temporary.replace(target)


class StubClient:
    """离线回放：只读 `fixtures/` 或 `calls/`，禁止任何网络请求（V-10）。"""

    def __init__(self, caps: ProviderCapabilities, replay_dir: str | Path) -> None:
        self.caps = caps
        self._dir = Path(replay_dir)

    def read(self, request: VisionRequest) -> VisionResponse:
        path = self._dir / f"{request.call_id}.resp.json"
        if not path.exists():
            raise ProviderError(ErrorCode.E_VLM_HTTP, f"回放文件不存在：{path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        content = data.get("content") or _content_of(data.get("raw", {}))
        if not content.strip():
            raise ProviderError(ErrorCode.E_VLM_EMPTY, f"回放为空：{path}")
        return VisionResponse(
            content=content,
            usage=data.get("usage", {}),
            duration_ms=int(data.get("durationMs", 0)),
            retry_count=0,
            raw=data.get("raw"),
        )


def _data_url(image: ImageInput) -> str:
    encoded = base64.b64encode(image.data).decode("ascii")
    return f"data:{image.media_type};base64,{encoded}"


def _content_of(data: dict) -> str:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    return message.get("content") or ""


def _backoff_http(attempt: int) -> float:
    return min(30.0, 2.0 ** (attempt - 1))


def _backoff_empty(attempt: int) -> float:
    return 1.0 if attempt == 1 else 3.0


def _retry_after(response: object, default: float) -> float:
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("Retry-After")
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _short(response: object) -> str:
    try:
        body = response.text  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - 只要一段摘要，失败也无所谓
        return ""
    return str(body)[:300]
