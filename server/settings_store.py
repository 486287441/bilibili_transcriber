"""Read/write runtime settings persisted to data/settings.json."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

import config

_SETTINGS_PATH = config.PROJECT_ROOT / "data" / "settings.json"
_lock = threading.Lock()

DEEPSEEK_MODELS = ("deepseek-v4-pro", "deepseek-v4-flash")


def _default_deepseek_model() -> str:
    model = config.DEEPSEEK_MODEL
    if model in DEEPSEEK_MODELS:
        return model
    return "deepseek-v4-pro"


class AppSettings(BaseModel):
    clipboard_enabled: bool = True
    autostart_enabled: bool = False
    auto_open_feishu: bool = False
    model_load_policy: str = Field(default="lazy", pattern="^(lazy|eager)$")
    model_idle_timeout_minutes: int = Field(default=30, ge=1, le=1440)
    deepseek_model: str = Field(
        default_factory=_default_deepseek_model,
        pattern="^(deepseek-v4-pro|deepseek-v4-flash)$",
    )
    recent_completed_dedup_minutes: int = Field(
        default=0,
        ge=0,
        le=10080,
        description="已废弃：去重改由历史记录控制，此字段保留兼容旧配置",
    )


def _ensure_data_dir() -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_settings() -> AppSettings:
    with _lock:
        if not _SETTINGS_PATH.is_file():
            return AppSettings()
        try:
            raw = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return AppSettings()
        if not isinstance(raw, dict):
            return AppSettings()
        return AppSettings.model_validate(raw)


def save_settings(settings: AppSettings) -> None:
    with _lock:
        _ensure_data_dir()
        _SETTINGS_PATH.write_text(
            settings.model_dump_json(indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def update_settings(partial: dict[str, Any]) -> AppSettings:
    current = load_settings()
    merged = current.model_dump()
    merged.update(partial)
    updated = AppSettings.model_validate(merged)
    save_settings(updated)
    return updated


def get_deepseek_model() -> str:
    return load_settings().deepseek_model


def should_auto_open_feishu() -> bool:
    return load_settings().auto_open_feishu
