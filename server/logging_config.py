"""Structured logging with request IDs and secret redaction."""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar
from pathlib import Path

import config

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_LOG_PATH = config.PROJECT_ROOT / "logs" / "server.log"

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}", re.IGNORECASE),
    re.compile(r"(DEEPSEEK_API_KEY)\s*[=:]\s*\S+", re.IGNORECASE),
)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("-")
        return True


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern in _SECRET_PATTERNS:
            message = pattern.sub("[REDACTED]", message)
        record.msg = message
        record.args = ()
        return True


def configure_logging(*, level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] [req=%(request_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(RequestIdFilter())
    stream_handler.addFilter(SecretRedactionFilter())
    root.addHandler(stream_handler)

    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(_LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(RequestIdFilter())
    file_handler.addFilter(SecretRedactionFilter())
    root.addHandler(file_handler)

    root.setLevel(level)


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]
