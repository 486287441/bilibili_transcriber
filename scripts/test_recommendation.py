"""Focused tests for recommendation prompting and Markdown parsing."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from prompts import OUTPUT_STRUCTURE, POLISH_AND_SUMMARY_SYSTEM
from server.recommendation import (
    apply_emotion_calibration,
    grade_for_score,
    normalize_recommendation,
    parse_recommendation,
    recommendation_for_scores,
    replace_recommendation,
)


def test_prompt_contract() -> None:
    assert "# 推荐指数" in OUTPUT_STRUCTURE
    assert "不得只写一句话主旨" in POLISH_AND_SUMMARY_SYSTEM
    assert "**核心内容**" in POLISH_AND_SUMMARY_SYSTEM
    assert "结论或事实 + 必要依据、数据、案例或影响" in POLISH_AND_SUMMARY_SYSTEM
    assert "内容价值分" in POLISH_AND_SUMMARY_SYSTEM
    assert "原片增量分" in POLISH_AND_SUMMARY_SYSTEM
    assert "娱乐内容不需要提供知识" in POLISH_AND_SUMMARY_SYSTEM
    assert "趣味与情绪回报" in POLISH_AND_SUMMARY_SYSTEM
    assert "男女对立再扣 30 分" in POLISH_AND_SUMMARY_SYSTEM
    assert "讨论性别问题不等于制造男女对立" in POLISH_AND_SUMMARY_SYSTEM
    assert "看总结即可」表示内容值得了解" in POLISH_AND_SUMMARY_SYSTEM
    assert "只能看到转写文字" in POLISH_AND_SUMMARY_SYSTEM
    assert "禁止评价或推测画质" in POLISH_AND_SUMMARY_SYSTEM
    assert "注意力质量" in POLISH_AND_SUMMARY_SYSTEM
    assert "全文软广" in POLISH_AND_SUMMARY_SYSTEM
    assert "通常扣 3～6 分" in POLISH_AND_SUMMARY_SYSTEM


def test_parser() -> None:
    markdown = """# 推荐指数
**推荐指数**：76/100（A）
**观看建议**：选看关键段
**判断理由**：一手访谈有独特经验，但背景铺陈可由总结替代。

# 视频总结
略
"""
    parsed = parse_recommendation(markdown)
    assert parsed is not None
    assert parsed["score"] == 76
    assert parsed["grade"] == "A"
    assert parsed["verdict"] == "推荐观看"
    assert parsed["advice"] == "选看关键段"
    assert parsed["is_dual_score"] is False


def test_parser_legacy_and_inconsistent_grade() -> None:
    assert parse_recommendation("# 视频总结\n旧文档") is None
    parsed = parse_recommendation(
        "# 推荐指数\n推荐指数：105/100（S）\n观看建议：完整看\n判断理由：测试\n"
    )
    assert parsed is not None
    assert parsed["score"] == 100
    assert parsed["grade"] == "S"
    assert grade_for_score(49) == "C"
    assert grade_for_score(50) == "B"
    assert grade_for_score(70) == "A"
    assert grade_for_score(85) == "S"

    new_format = """# 推荐指数
**推荐结论**：不推荐
**推荐等级**：B
**推荐分数**：68/100
**观看建议**：看总结即可
**广告判断**：全文软广
**打分依据**：内容可信，但总结已覆盖主要信息。
**推荐理由**：完整内容的新增价值不足以抵消注意力成本。
"""
    new_parsed = parse_recommendation(new_format)
    assert new_parsed is not None
    assert new_parsed["verdict"] == "值得了解"
    assert new_parsed["grade"] == "B"
    assert new_parsed["advice"] == "看总结即可"
    assert new_parsed["advertising"] == "全文软广"
    assert new_parsed["scoring_reason"] == "内容可信，但总结已覆盖主要信息。"
    assert new_parsed["recommendation_reason"] == "完整内容的新增价值不足以抵消注意力成本。"


def test_dual_score_mapping_and_normalization() -> None:
    assert recommendation_for_scores(49, 100) == {
        "grade": "C",
        "verdict": "可略过",
        "advice": "不必看",
    }
    assert recommendation_for_scores(70, 49) == {
        "grade": "B",
        "verdict": "值得了解",
        "advice": "看总结即可",
    }
    assert recommendation_for_scores(69, 90)["grade"] == "A"
    assert recommendation_for_scores(70, 84)["grade"] == "A"
    assert recommendation_for_scores(70, 85) == {
        "grade": "S",
        "verdict": "推荐观看",
        "advice": "完整看",
    }

    raw = """# 推荐指数
**内容类型**：观点分析
**基础内容价值分**：78/100
**原片增量分**：42/100
**负面情绪风险**：低
**对立煽动判断**：无
**广告判断**：无明显广告
**内容价值依据**：包含一手经验和可执行建议。
**原片增量依据**：总结已经覆盖主要结论，原片多为重复展开。
**情绪风险依据**：严肃讨论但表达克制，没有煽动群体敌意。
**综合判断**：内容值得了解，但阅读总结是更高效的消费方式。

# 视频总结
摘要
"""
    parsed = parse_recommendation(raw)
    assert parsed is not None
    assert parsed["content_score"] == 78
    assert parsed["incremental_score"] == 42
    assert parsed["content_type"] == "观点分析"
    assert parsed["base_content_score"] == 78
    assert parsed["emotion_penalty"] == 0
    assert parsed["grade"] == "B"
    assert parsed["verdict"] == "值得了解"
    assert parsed["advice"] == "看总结即可"

    normalized = normalize_recommendation(raw)
    assert "**内容结论**：值得了解" in normalized
    assert "**推荐等级**：B" in normalized
    assert "**内容类型**：观点分析" in normalized
    assert "**负面情绪风险**：低" in normalized
    assert "**观看建议**：看总结即可" in normalized
    assert normalized.count("# 推荐指数") == 1
    assert "**综合判断**：内容值得了解，但阅读总结是更高效的消费方式。\n\n# 视频总结" in normalized


def test_emotion_and_gender_antagonism_penalties() -> None:
    assert apply_emotion_calibration(80, "低", "无") == (80, 0)
    assert apply_emotion_calibration(80, "中", "一般对立") == (60, 20)
    assert apply_emotion_calibration(95, "高", "男女对立") == (47, 48)
    # 男女对立即使基础分很高，也不得越过 C 级上限。
    assert apply_emotion_calibration(100, "低", "男女对立") == (49, 51)


def test_replace_recommendation() -> None:
    old_article = "# 视频总结\n旧总结\n\n# 原文\n旧原文"
    section = """# 推荐指数
**推荐指数**：61/100（B）
**观看建议**：看总结即可
**判断理由**：核心信息可由总结替代。
"""
    updated = replace_recommendation(old_article, section)
    assert updated.startswith("# 推荐指数\n")
    assert updated.count("# 推荐指数") == 1
    assert updated.endswith(old_article)

    replacement = section.replace("61/100（B）", "88/100（S）")
    replaced = replace_recommendation(updated, replacement)
    assert replaced.count("# 推荐指数") == 1
    assert "**推荐分数**：88/100" in replaced
    assert "61/100（B）" not in replaced


if __name__ == "__main__":
    test_prompt_contract()
    test_parser()
    test_parser_legacy_and_inconsistent_grade()
    test_dual_score_mapping_and_normalization()
    test_emotion_and_gender_antagonism_penalties()
    test_replace_recommendation()
    print("recommendation tests PASS")
