"""派生自 kouqiang-beikao；有界响应、真实 SSE、错误脱敏，仅服务端读取密钥。"""

from __future__ import annotations

import asyncio
import base64
import codecs
import json
import math
import os
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from .contracts import AiError, ModelDelta, ModelRequest, ModelResult

# 模型名称和接口地址由用户配置，不内置服务商凭据。
DEFAULT_BASE_URL = ""
DEFAULT_MODEL = ""


def _invalid_config() -> AiError:
    return AiError("model_unavailable", "模型配置无效，请检查接口地址、模型名称和密钥", 503)


@dataclass(frozen=True)
class ProviderConfig:
    api_key: str = field(default="", repr=False)
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    allow_no_key: bool = False
    total_timeout: float = 180.0
    read_timeout: float = 90.0
    connect_timeout: float = 5.0
    max_retries: int = 0
    retry_delay: float = 0.2
    max_response_bytes: int = 262144
    max_event_bytes: int = 65536
    max_tokens: int = 8192

    def __post_init__(self) -> None:
        try:
            url = urlsplit(self.base_url)
            # 开发环境只允许显式配置的本机 HTTP；不接受凭据、查询串或重定向。
            safe_scheme = url.scheme == "https" or (
                url.scheme == "http"
                and url.hostname in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
            )
            if (
                not safe_scheme
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError
            _ = url.port
            if any(ord(char) < 33 for char in self.base_url):
                raise ValueError
            if (
                not self.model.strip()
                or len(self.model) > 200
                or any(ord(c) < 32 for c in self.model)
            ):
                raise ValueError
            if len(self.api_key) > 4096 or any(not 33 <= ord(c) <= 126 for c in self.api_key):
                raise ValueError
            for number in (self.total_timeout, self.read_timeout, self.connect_timeout):
                if not math.isfinite(number) or not 0 < number <= 600:
                    raise ValueError
            if not math.isfinite(self.retry_delay) or not 0 <= self.retry_delay <= 5:
                raise ValueError
            if type(self.max_retries) is not int or self.max_retries not in (0, 1, 2):
                raise ValueError
            for number, lower, upper in (
                (self.max_response_bytes, 256, 4 * 1024 * 1024),
                (self.max_event_bytes, 128, 1024 * 1024),
                (self.max_tokens, 1, 32768),
            ):
                if type(number) is not int or not lower <= number <= upper:
                    raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise _invalid_config() from None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ProviderConfig:
        values = os.environ if env is None else env
        return cls(
            api_key=values.get("STUDY_MODEL_API_KEY", ""),
            base_url=values.get("STUDY_MODEL_BASE_URL", ""),
            model=values.get("STUDY_MODEL_NAME", ""),
        )


def _protocol_error(code: str = "model_invalid_response") -> AiError:
    return AiError(code, "模型服务返回了无效或不完整的内容", 502)


def _json_object(text: str) -> dict:
    try:
        value = json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict):
            raise TypeError
        return value
    except (TypeError, ValueError, RecursionError):
        raise _protocol_error() from None


def _usage(value: object) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _protocol_error()
    # 不把服务商提供的任意文本/元数据透传给调用方。
    return {
        key: amount
        for key, amount in value.items()
        if key
        in {
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
        }
        and type(amount) is int
        and amount >= 0
    }


def _finish(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 64:
        raise _protocol_error()
    return value


class OpenAICompatibleProvider:
    """可注入 httpx 客户端；注入的客户端生命周期由调用者负责。"""

    def __init__(
        self, config: ProviderConfig | None = None, client: httpx.AsyncClient | None = None
    ):
        self.config = config if config is not None else ProviderConfig.from_env()
        self._client = client
        self._request_client = ContextVar("ai_request_client", default=None)

    def _valid_content(self, message):
        content = message.get("content")
        if isinstance(content, str):
            return True
        if self.config.model != "glm-5.3-flash" or message.get("role") != "user":
            return False
        if not isinstance(content, list) or not 1 <= len(content) <= 7:
            return False
        for part in content:
            if not isinstance(part, dict):
                return False
            if part.get("type") == "text" and set(part) == {"type", "text"}:
                if not isinstance(part["text"], str):
                    return False
            elif part.get("type") == "image_url" and set(part) == {"type", "image_url"}:
                image = part["image_url"]
                if not isinstance(image, dict) or set(image) != {"url"}:
                    return False
                url = image["url"]
                if not isinstance(url, str) or len(url) > 720_000:
                    return False
                match = re.fullmatch(r"data:image/(jpeg|png);base64,([A-Za-z0-9+/=]+)", url)
                if not match:
                    return False
                try:
                    raw = base64.b64decode(match[2], validate=True)
                except ValueError:
                    return False
                if (
                    not raw
                    or len(raw) > 512_000
                    or not raw.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"))
                ):
                    return False
            else:
                return False
        return True

    def _payload(self, request: ModelRequest, stream: bool) -> dict:
        if not self.config.api_key and not self.config.allow_no_key:
            raise AiError("model_unavailable", "模型服务未配置，暂时无法使用 AI", 503)
        if not request.messages or any(
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or not isinstance(message.get("role"), str)
            or message.get("role") not in {"system", "user", "assistant"}
            or not self._valid_content(message)
            for message in request.messages
        ):
            raise AiError("model_invalid_request", "模型请求格式无效", 400)
        payload = {
            "model": self.config.model,
            "messages": request.messages,
            "stream": stream,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.model == "deepseek-flash":
            payload["thinking"] = {"type": "disabled"}
        elif self.config.model == "glm-5.3-flash":
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = "low"
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    @asynccontextmanager
    async def request_session(self):
        """同一问答的生成、核验与修正共用连接；不同请求按协程隔离。"""
        if self._client is not None or self._request_client.get() is not None:
            yield
            return
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
            token = self._request_client.set(client)
            try:
                yield
            finally:
                self._request_client.reset(token)

    @asynccontextmanager
    async def _session(self):
        client = self._client if self._client is not None else self._request_client.get()
        if client is not None:
            yield client
        else:
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
                yield client

    def _request_args(self, stream: bool = False) -> dict:
        return {
            "url": self.config.base_url.rstrip("/") + "/chat/completions",
            "headers": {
                **(
                    {"Authorization": "Bearer " + self.config.api_key}
                    if self.config.api_key
                    else {}
                ),
                "Accept": "text/event-stream" if stream else "application/json",
            },
            "timeout": httpx.Timeout(self.config.read_timeout, connect=self.config.connect_timeout),
            "follow_redirects": False,
        }

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        if status in (401, 403):
            raise AiError("model_unavailable", "模型认证失败，请检查 API 密钥和接口权限", 503)
        if status == 402:
            raise AiError("model_balance_empty", "模型服务余额不足，请使用另一模型", 503)
        if status == 408:
            raise AiError("model_timeout", "模型服务响应超时，请稍后重试", 504, True)
        if status == 429:
            raise AiError("model_rate_limited", "模型服务繁忙，请稍后重试", 503, True)
        if status >= 500:
            raise AiError("model_upstream_error", "模型服务暂时不可用", 503, True)
        raise AiError("model_upstream_error", "模型请求失败，请检查接口地址与模型名称", 502)

    @staticmethod
    def _transport_error(error: httpx.HTTPError) -> AiError:
        if isinstance(error, httpx.TimeoutException):
            return AiError("model_timeout", "模型服务响应超时，请稍后重试", 504, True)
        return AiError("model_upstream_error", "模型服务连接中断，请稍后重试", 503, True)

    async def _backoff(self, attempt: int) -> None:
        await asyncio.sleep(self.config.retry_delay * (2**attempt))

    def _check_model(self, parsed: dict) -> None:
        if "model" in parsed and (not isinstance(parsed["model"], str) or not parsed["model"]):
            raise _protocol_error("model_mismatch")

    async def complete(self, request: ModelRequest) -> ModelResult:
        payload = self._payload(request, False)
        try:
            async with asyncio.timeout(self.config.total_timeout), self._session() as client:
                for attempt in range(self.config.max_retries + 1):
                    try:
                        # 使用流式读取限制非 SSE 响应的内存，含异常/恶意上游响应。
                        async with client.stream(
                            "POST", json=payload, **self._request_args()
                        ) as response:
                            self._check_status(response)
                            body = bytearray()
                            async for chunk in response.aiter_bytes():
                                if len(body) + len(chunk) > self.config.max_response_bytes:
                                    raise _protocol_error("model_response_too_large")
                                body.extend(chunk)
                            try:
                                parsed = _json_object(body.decode("utf-8"))
                            except UnicodeError:
                                raise _protocol_error() from None
                            self._check_model(parsed)
                            choices = parsed.get("choices")
                            if (
                                not isinstance(choices, list)
                                or len(choices) != 1
                                or not isinstance(choices[0], dict)
                            ):
                                raise _protocol_error()
                            choice = choices[0]
                            message = choice.get("message")
                            reason = _finish(choice.get("finish_reason"))
                            if (
                                not isinstance(message, dict)
                                or not self._valid_content(message)
                                or reason is None
                            ):
                                raise _protocol_error()
                            text = message["content"]
                            if request.json_mode:
                                _json_object(text)
                            return ModelResult(
                                text, self.config.model, _usage(parsed.get("usage")), reason
                            )
                    except httpx.HTTPError as error:
                        failure = self._transport_error(error)
                    except AiError as error:
                        failure = error
                    if not failure.retryable or attempt == self.config.max_retries:
                        raise failure from None
                    await self._backoff(attempt)
        except TimeoutError:
            raise AiError("model_timeout", "模型服务响应超时，请稍后重试", 504) from None

    async def _events(self, response: httpx.Response) -> AsyncIterator[str]:
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        buffer = ""
        data: list[str] = []
        event_bytes = 0
        total_bytes = 0

        async def chunks():
            async for chunk in response.aiter_bytes():
                yield chunk, False
            yield b"", True

        try:
            async for chunk, eof in chunks():
                total_bytes += len(chunk)
                if total_bytes > self.config.max_response_bytes:
                    raise _protocol_error("model_response_too_large")
                buffer += decoder.decode(chunk, final=eof)
                while match := re.search(r"\r\n|\r|\n", buffer):
                    # CRLF 可能跨网络分块，不能把末尾 CR 先当作独立分隔。
                    if not eof and match.group() == "\r" and match.end() == len(buffer):
                        break
                    line, buffer = buffer[: match.start()], buffer[match.end() :]
                    if not line:
                        if data:
                            yield "\n".join(data)
                        data, event_bytes = [], 0
                    else:
                        event_bytes += len(line.encode("utf-8"))
                        if event_bytes > self.config.max_event_bytes:
                            raise _protocol_error("model_response_too_large")
                        if line.startswith("data:"):
                            data.append(line[5:].removeprefix(" "))
                if len(buffer.encode("utf-8")) + event_bytes > self.config.max_event_bytes:
                    raise _protocol_error("model_response_too_large")
        except UnicodeError:
            raise _protocol_error() from None
        # SSE 事件须以空行终止；残留半行/半个事件不能冒充完整响应。
        if buffer.strip() or data:
            raise _protocol_error("model_stream_interrupted")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelDelta]:
        payload = self._payload(request, True)
        started = False
        terminal = None
        try:
            async with asyncio.timeout(self.config.total_timeout), self._session() as client:
                for attempt in range(self.config.max_retries + 1):
                    try:
                        reason = None
                        content: list[str] = []
                        usage: dict[str, int] = {}
                        async with client.stream(
                            "POST", json=payload, **self._request_args(stream=True)
                        ) as response:
                            self._check_status(response)
                            async for event in self._events(response):
                                if event == "[DONE]":
                                    if reason is None:
                                        raise _protocol_error("model_stream_interrupted")
                                    break
                                parsed = _json_object(event)
                                self._check_model(parsed)
                                if "error" in parsed:
                                    raise AiError("model_upstream_error", "模型服务生成失败", 502)
                                usage.update(_usage(parsed.get("usage")))
                                choices = parsed.get("choices")
                                if not isinstance(choices, list) or len(choices) > 1:
                                    raise _protocol_error()
                                if not choices:
                                    continue
                                choice = choices[0]
                                if not isinstance(choice, dict) or not isinstance(
                                    choice.get("delta"), dict
                                ):
                                    raise _protocol_error()
                                delta = choice["delta"]
                                # 隐藏的 reasoning token 也意味着生成已开始，不允许重放。
                                if (
                                    delta.get("content")
                                    or delta.get("reasoning_content")
                                    or delta.get("tool_calls")
                                ):
                                    started = True
                                text = delta.get("content")
                                if text is not None and not isinstance(text, str):
                                    raise _protocol_error()
                                if reason is not None and text:
                                    raise _protocol_error()
                                if text:
                                    content.append(text)
                                    yield ModelDelta(text=text)
                                finish = _finish(choice.get("finish_reason"))
                                if finish is not None:
                                    started = True
                                    reason = finish
                            if reason is None:
                                raise _protocol_error("model_stream_interrupted")
                            if request.json_mode:
                                _json_object("".join(content))
                        terminal = ModelDelta(finish_reason=reason, usage=usage)
                        break
                    except httpx.HTTPError as error:
                        failure = self._transport_error(error)
                        if started:
                            failure = AiError(
                                "model_stream_interrupted", "模型回答已中断，请重新发起提问", 502
                            )
                    except AiError as error:
                        failure = error
                    if started or not failure.retryable or attempt == self.config.max_retries:
                        raise failure from None
                    await self._backoff(attempt)
        except TimeoutError:
            raise AiError("model_timeout", "模型服务响应超时，请稍后重试", 504) from None
        # 在交付完成事件之前关闭响应、owned client 与超时上下文；调用者
        # 收到 finish 后停止读取，也不会残留上游连接或取消调用者的计时器。
        if terminal is not None:
            yield terminal
