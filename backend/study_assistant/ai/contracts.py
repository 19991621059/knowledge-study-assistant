"""沿用 kouqiang-beikao 的服务端模型请求与错误契约。"""

from dataclasses import dataclass, field
from typing import Any


class AiError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 503, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True)
class ModelRequest:
    messages: list[dict[str, Any]]
    purpose: str
    json_mode: bool = False


@dataclass(frozen=True)
class ModelResult:
    text: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = "stop"


@dataclass(frozen=True)
class ModelDelta:
    text: str = ""
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
