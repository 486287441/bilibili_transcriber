"""Read/write runtime settings persisted to data/settings.json."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

import config

_SETTINGS_PATH = config.PROJECT_ROOT / "data" / "settings.json"
_lock = threading.Lock()

DEEPSEEK_MODELS = ("deepseek-v4-pro", "deepseek-v4-flash")

DEFAULT_FEISHU_TITLE_TEMPLATE = "{{date}} {{title}}"
DEFAULT_FEISHU_DOCUMENT_TEMPLATE = """{{body}}

---

**标题：** {{title}}

**链接：** {{url}}

**转写时间：** {{transcribed_at}}

{{stats}}"""


def _default_deepseek_model() -> str:
    model = config.DEEPSEEK_MODEL
    if model in DEEPSEEK_MODELS:
        return model
    return "deepseek-v4-pro"


def _default_recommendation_criteria() -> str:
    from prompts import VIDEO_RECOMMENDATION_RULES

    return VIDEO_RECOMMENDATION_RULES


def _default_polish_prompt_template() -> str:
    from prompts import POLISH_PROMPT_TEMPLATE

    return POLISH_PROMPT_TEMPLATE


def _default_transcript_correction_prompt() -> str:
    from prompts import TRANSCRIPT_CORRECTION_SYSTEM

    return TRANSCRIPT_CORRECTION_SYSTEM


class AppSettings(BaseModel):
    clipboard_enabled: bool = True
    auto_open_feishu: bool = False
    model_load_policy: str = Field(default="lazy", pattern="^(lazy|eager)$")
    model_idle_timeout_minutes: int = Field(default=30, ge=1, le=1440)
    deepseek_model: str = Field(
        default_factory=_default_deepseek_model,
        pattern="^(deepseek-v4-pro|deepseek-v4-flash)$",
    )
    recommendation_criteria: str = Field(
        default_factory=_default_recommendation_criteria,
        min_length=20,
        max_length=50000,
    )
    transcript_correction_prompt: str = Field(
        default_factory=_default_transcript_correction_prompt,
        min_length=20,
        max_length=50000,
    )
    polish_prompt_template: str = Field(
        default_factory=_default_polish_prompt_template,
        min_length=20,
        max_length=100000,
    )
    feishu_title_template: str = Field(
        default=DEFAULT_FEISHU_TITLE_TEMPLATE,
        min_length=1,
        max_length=500,
    )
    feishu_document_template: str = Field(
        default=DEFAULT_FEISHU_DOCUMENT_TEMPLATE,
        min_length=10,
        max_length=50000,
    )
    recent_completed_dedup_minutes: int = Field(
        default=0,
        ge=0,
        le=10080,
        description="已废弃：去重改由历史记录控制，此字段保留兼容旧配置",
    )

    @field_validator(
        "recommendation_criteria",
        "transcript_correction_prompt",
        "polish_prompt_template",
        "feishu_title_template",
        "feishu_document_template",
    )
    @classmethod
    def _strip_editable_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("feishu_document_template")
    @classmethod
    def _require_body_placeholder(cls, value: str) -> str:
        if "{{body}}" not in value:
            raise ValueError("飞书正文模板必须包含 {{body}} 占位符")
        return value


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


def get_recommendation_criteria() -> str:
    return load_settings().recommendation_criteria


def get_transcript_correction_prompt() -> str:
    return load_settings().transcript_correction_prompt


def get_polish_prompt_template() -> str:
    return load_settings().polish_prompt_template


def editable_defaults() -> dict[str, str]:
    return {
        "recommendation_criteria": _default_recommendation_criteria(),
        "transcript_correction_prompt": _default_transcript_correction_prompt(),
        "polish_prompt_template": _default_polish_prompt_template(),
        "feishu_title_template": DEFAULT_FEISHU_TITLE_TEMPLATE,
        "feishu_document_template": DEFAULT_FEISHU_DOCUMENT_TEMPLATE,
    }


def should_auto_open_feishu() -> bool:
    return load_settings().auto_open_feishu
