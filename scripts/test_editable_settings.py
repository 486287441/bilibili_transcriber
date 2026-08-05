"""Focused tests for editable prompts and Feishu document templates."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from feishu_client import _render_template, _wiki_doc_title
from prompts import render_polish_system
from server.settings_store import AppSettings, editable_defaults


def test_editable_defaults() -> None:
    defaults = editable_defaults()
    assert "全文软广" in defaults["recommendation_criteria"]
    assert "{{recommendation_criteria}}" in defaults["polish_prompt_template"]
    assert "{{body}}" in defaults["feishu_document_template"]
    assert AppSettings().feishu_title_template == "{{date}} {{title}}"


def test_prompt_rendering() -> None:
    assert render_polish_system("前文\n{{recommendation_criteria}}\n后文", "推荐规则") == (
        "前文\n推荐规则\n后文"
    )
    assert render_polish_system("前文", "推荐规则") == "前文\n\n推荐规则"


def test_feishu_template_rendering() -> None:
    when = datetime(2026, 7, 19, 9, 30)
    assert _wiki_doc_title("示例 视频", when, "{{date}}｜{{title}}") == "2026-07-19｜示例 视频"
    assert _render_template("# {{title}}\n\n{{body}}", {"title": "标题", "body": "正文"}) == (
        "# 标题\n\n正文"
    )


def test_feishu_body_placeholder_is_required() -> None:
    try:
        AppSettings(feishu_document_template="# 只有标题，没有正文占位符")
    except ValidationError as exc:
        assert "{{body}}" in str(exc)
    else:
        raise AssertionError("missing {{body}} should fail validation")


if __name__ == "__main__":
    test_editable_defaults()
    test_prompt_rendering()
    test_feishu_template_rendering()
    test_feishu_body_placeholder_is_required()
    print("editable settings tests PASS")
