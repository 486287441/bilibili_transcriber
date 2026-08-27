"""Focused tests for ASR cleanup and the two-stage DeepSeek flow."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Keep this focused unit test runnable even when the project's optional cloud
# dependencies are not installed in the current Python interpreter.
sys.modules.setdefault(
    "openai",
    SimpleNamespace(
        APIConnectionError=type("APIConnectionError", (Exception,), {}),
        APIStatusError=type("APIStatusError", (Exception,), {}),
        APITimeoutError=type("APITimeoutError", (Exception,), {}),
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
        OpenAI=object,
        RateLimitError=type("RateLimitError", (Exception,), {}),
    ),
)
sys.modules.setdefault("config", SimpleNamespace(DEEPSEEK_API_KEY="", DEEPSEEK_BASE_URL=""))
sys.modules.setdefault(
    "server.settings_store",
    SimpleNamespace(
        get_deepseek_model=lambda: "test-model",
        get_polish_prompt_template=lambda: "第二阶段内容整理",
        get_transcript_correction_prompt=lambda: "第一阶段测试 Prompt",
        is_first_stage_enabled=lambda: True,
        is_second_stage_enabled=lambda: True,
    ),
)
from deepseek_client import process_transcript, stream_chat_about_article
from prompts import TRANSCRIPT_CORRECTION_SYSTEM, render_polish_system
from transcript_processing import format_transcript_locally, remove_asr_punctuation


def test_first_stage_prompt_contract() -> None:
    assert TRANSCRIPT_CORRECTION_SYSTEM.startswith(
        "这是语音识别生成的无标点转写稿，其中可能存在错字、同音近音误识别、漏字、多字和专有名词识别错误。"
    )
    assert "请根据上下文恢复说话人最可能的原话" in TRANSCRIPT_CORRECTION_SYSTEM
    assert "不得仅为了让句子更优美而修改文字" in TRANSCRIPT_CORRECTION_SYSTEM
    assert TRANSCRIPT_CORRECTION_SYSTEM.endswith("只输出校对后的完整转写稿。")


def test_remove_only_natural_language_punctuation() -> None:
    source = (
        "价格3.5，显卡4060。模型GPT-5！语言C++？实验A/B；完成20%："
        "地址192.168.1.1、日期2026-08-09……继续——“引号”（括号）"
    )
    assert remove_asr_punctuation(source) == (
        "价格3.5显卡4060模型GPT-5语言C++实验A/B完成20%"
        "地址192.168.1.1日期2026-08-09继续“引号”（括号）"
    )


def test_two_separate_deepseek_calls() -> None:
    calls: list[dict] = []
    outputs = iter([
        "第一阶段：可信逐字稿。",
        "# 视频总结\n总结\n\n# 目录\n\n# 原文\n可信逐字稿。",
    ])

    def create(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(content=next(outputs))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with (
        patch("deepseek_client._client", return_value=fake_client),
        patch("deepseek_client.get_deepseek_model", return_value="test-model"),
        patch("deepseek_client.get_transcript_correction_prompt", return_value=TRANSCRIPT_CORRECTION_SYSTEM),
        patch("deepseek_client.get_polish_prompt_template", return_value="第二阶段内容整理"),
    ):
        trusted, article = process_transcript("版本GPT-5，数值3.5。")

    assert trusted == "第一阶段：可信逐字稿。"
    assert article.startswith("# 视频总结")
    assert len(calls) == 2
    assert calls[0]["messages"][0]["content"] == TRANSCRIPT_CORRECTION_SYSTEM
    assert calls[0]["messages"][1]["content"] == "版本GPT-5数值3.5"
    assert "第一阶段：可信逐字稿。" in calls[1]["messages"][1]["content"]
    assert all(
        call["extra_body"] == {"thinking": {"type": "disabled"}}
        for call in calls
    )


def test_local_formatter_preserves_asr_punctuation_and_words() -> None:
    source = "第一句，有标点。第二句也有！第三句？"
    formatted = format_transcript_locally(source, target_paragraph_chars=8)
    assert formatted == "第一句，有标点。\n\n第二句也有！\n\n第三句？"
    assert formatted.replace("\n", "") == source
    assert format_transcript_locally("中文第一行\n中文第二行") == "中文第一行中文第二行"
    assert format_transcript_locally("OpenAI API\nresponse") == "OpenAI API response"


def test_second_stage_can_be_disabled() -> None:
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(content="第一阶段：可直接发布的完整转写稿。")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with (
        patch("deepseek_client._client", return_value=fake_client),
        patch("deepseek_client.get_deepseek_model", return_value="test-model"),
        patch("deepseek_client.get_transcript_correction_prompt", return_value=TRANSCRIPT_CORRECTION_SYSTEM),
        patch("deepseek_client.is_second_stage_enabled", return_value=False),
    ):
        trusted, article = process_transcript("没有标点的原始字幕")

    assert trusted == "第一阶段：可直接发布的完整转写稿。"
    assert article == trusted
    assert len(calls) == 1


def test_first_stage_disabled_uses_local_format_and_skips_all_deepseek() -> None:
    with (
        patch("deepseek_client.is_first_stage_enabled", return_value=False),
        patch("deepseek_client.is_second_stage_enabled", return_value=True),
        patch("deepseek_client.correct_transcript") as correct,
        patch("deepseek_client.organize_transcript") as organize,
    ):
        trusted, article = process_transcript("第一句，有标点。第二句也有！")

    assert trusted == "第一句，有标点。第二句也有！"
    assert article == trusted
    correct.assert_not_called()
    organize.assert_not_called()


def test_followup_explicitly_disables_thinking() -> None:
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        delta = SimpleNamespace(content="直接回答", reasoning_content=None)
        return [SimpleNamespace(choices=[SimpleNamespace(delta=delta)])]

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with (
        patch("deepseek_client._client", return_value=fake_client),
        patch("deepseek_client.get_deepseek_model", return_value="test-model"),
    ):
        events = list(
            stream_chat_about_article(
                "文章正文",
                [{"role": "user", "content": "文章结论是什么？"}],
            )
        )

    assert calls[0]["stream"] is True
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert not any(event["type"] == "thinking" for event in events)
    assert events[-1]["reply"] == "直接回答"


def test_persisted_legacy_second_stage_prompt_is_upgraded() -> None:
    legacy = "前文\n**步骤 B — 纠错与整理**\n旧纠错规则\n**步骤 C — 章节划分原则**\n后文"
    rendered = render_polish_system(legacy)
    assert "输入是已校对的可信逐字稿" in rendered
    assert "不再纠错、润色或改写" in rendered
    assert "旧纠错规则" not in rendered
    assert "**步骤 C — 章节划分原则**" in rendered


if __name__ == "__main__":
    test_first_stage_prompt_contract()
    test_remove_only_natural_language_punctuation()
    test_local_formatter_preserves_asr_punctuation_and_words()
    test_two_separate_deepseek_calls()
    test_second_stage_can_be_disabled()
    test_first_stage_disabled_uses_local_format_and_skips_all_deepseek()
    test_followup_explicitly_disables_thinking()
    test_persisted_legacy_second_stage_prompt_is_upgraded()
    print("two-stage pipeline tests PASS")
