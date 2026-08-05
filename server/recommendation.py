"""Parse the machine-readable recommendation block from polished Markdown."""

from __future__ import annotations

import re
from typing import Any


_SECTION_RE = re.compile(
    r"(?ms)^#\s+推荐指数\s*$\n(?P<body>.*?)(?=^#\s+|\Z)"
)
_SCORE_RE = re.compile(
    r"\*{0,2}(?:推荐指数|推荐分数)\*{0,2}\s*[：:]\s*(?P<score>\d{1,3})(?:\.\d+)?\s*/\s*100"
    r"(?:\s*[（(]\s*(?P<grade>[SABC])\s*[）)])?",
    re.IGNORECASE,
)
_CONTENT_SCORE_RE = re.compile(
    r"\*{0,2}内容价值分\*{0,2}\s*[：:]\s*(?P<score>\d{1,3})(?:\.\d+)?\s*/\s*100"
)
_BASE_CONTENT_SCORE_RE = re.compile(
    r"\*{0,2}基础内容价值分\*{0,2}\s*[：:]\s*(?P<score>\d{1,3})(?:\.\d+)?\s*/\s*100"
)
_INCREMENTAL_SCORE_RE = re.compile(
    r"\*{0,2}原片增量分\*{0,2}\s*[：:]\s*(?P<score>\d{1,3})(?:\.\d+)?\s*/\s*100"
)
_CONTENT_TYPE_RE = re.compile(
    r"\*{0,2}内容类型\*{0,2}\s*[：:]\s*"
    r"(?P<value>知识信息|实用教程|观点分析|娱乐体验|混合型)"
)
_NEGATIVE_EMOTION_RE = re.compile(
    r"\*{0,2}负面情绪风险\*{0,2}\s*[：:]\s*(?P<value>低|中|高)"
)
_ANTAGONISM_RE = re.compile(
    r"\*{0,2}对立煽动判断\*{0,2}\s*[：:]\s*"
    r"(?P<value>无|一般对立|男女对立)"
)
_VERDICT_RE = re.compile(
    r"\*{0,2}(?:推荐结论|内容结论)\*{0,2}\s*[：:]\s*"
    r"(?P<value>推荐观看|值得了解|可略过|推荐|不推荐)"
)
_GRADE_RE = re.compile(
    r"\*{0,2}推荐等级\*{0,2}\s*[：:]\s*(?P<value>[SABC])",
    re.IGNORECASE,
)
_ADVICE_RE = re.compile(
    r"\*{0,2}观看建议\*{0,2}\s*[：:]\s*(?P<value>[^\n]+)"
)
_ADVERTISING_RE = re.compile(
    r"\*{0,2}广告判断\*{0,2}\s*[：:]\s*(?P<value>[^\n]+)"
)
_REASON_RE = re.compile(
    r"\*{0,2}判断理由\*{0,2}\s*[：:]\s*(?P<value>[^\n]+)"
)
_SCORING_REASON_RE = re.compile(
    r"\*{0,2}打分依据\*{0,2}\s*[：:]\s*(?P<value>[^\n]+)"
)
_RECOMMENDATION_REASON_RE = re.compile(
    r"\*{0,2}推荐理由\*{0,2}\s*[：:]\s*(?P<value>[^\n]+)"
)
_CONTENT_REASON_RE = re.compile(
    r"\*{0,2}内容价值依据\*{0,2}\s*[：:]\s*(?P<value>[^\n]+)"
)
_INCREMENTAL_REASON_RE = re.compile(
    r"\*{0,2}原片增量依据\*{0,2}\s*[：:]\s*(?P<value>[^\n]+)"
)
_OVERALL_REASON_RE = re.compile(
    r"\*{0,2}综合判断\*{0,2}\s*[：:]\s*(?P<value>[^\n]+)"
)
_EMOTION_REASON_RE = re.compile(
    r"\*{0,2}情绪风险依据\*{0,2}\s*[：:]\s*(?P<value>[^\n]+)"
)


def grade_for_score(score: int) -> str:
    """Legacy single-score grade mapping."""
    if score >= 85:
        return "S"
    if score >= 70:
        return "A"
    if score >= 50:
        return "B"
    return "C"


def recommendation_for_scores(content_score: int, incremental_score: int) -> dict[str, str]:
    """Derive the canonical result from content value and original-video increment."""
    content = max(0, min(100, int(content_score)))
    incremental = max(0, min(100, int(incremental_score)))
    if content < 50:
        return {"grade": "C", "verdict": "可略过", "advice": "不必看"}
    if incremental < 50:
        return {"grade": "B", "verdict": "值得了解", "advice": "看总结即可"}
    if content >= 70 and incremental >= 85:
        return {"grade": "S", "verdict": "推荐观看", "advice": "完整看"}
    return {"grade": "A", "verdict": "推荐观看", "advice": "选看关键段"}


def apply_emotion_calibration(
    base_content_score: int,
    negative_emotion: str,
    antagonism: str,
) -> tuple[int, int]:
    """Apply fixed penalties for emotional manipulation and group antagonism."""
    base = max(0, min(100, int(base_content_score)))
    penalty = {"低": 0, "中": 8, "高": 18}.get(negative_emotion, 0)
    penalty += {"无": 0, "一般对立": 12, "男女对立": 30}.get(antagonism, 0)
    adjusted = max(0, base - penalty)
    if antagonism == "男女对立":
        adjusted = min(adjusted, 49)
    return adjusted, base - adjusted


def _legacy_result_for_grade(grade: str) -> dict[str, str]:
    if grade == "S":
        return {"verdict": "推荐观看", "advice": "完整看"}
    if grade == "A":
        return {"verdict": "推荐观看", "advice": "选看关键段"}
    if grade == "B":
        return {"verdict": "值得了解", "advice": "看总结即可"}
    return {"verdict": "可略过", "advice": "不必看"}


def _clean(value: str) -> str:
    return value.strip().strip("* ")


def parse_recommendation(markdown: str | None) -> dict[str, Any] | None:
    """Parse dual-score recommendations while remaining compatible with old articles."""
    if not markdown:
        return None
    section = _SECTION_RE.search(markdown)
    if not section:
        return None
    body = section.group("body")
    base_content_score_match = _BASE_CONTENT_SCORE_RE.search(body)
    content_score_match = _CONTENT_SCORE_RE.search(body)
    incremental_score_match = _INCREMENTAL_SCORE_RE.search(body)
    content_type_match = _CONTENT_TYPE_RE.search(body)
    negative_emotion_match = _NEGATIVE_EMOTION_RE.search(body)
    antagonism_match = _ANTAGONISM_RE.search(body)
    advertising_match = _ADVERTISING_RE.search(body)
    content_reason_match = _CONTENT_REASON_RE.search(body)
    incremental_reason_match = _INCREMENTAL_REASON_RE.search(body)
    overall_reason_match = _OVERALL_REASON_RE.search(body)
    emotion_reason_match = _EMOTION_REASON_RE.search(body)

    effective_content_match = base_content_score_match or content_score_match
    if effective_content_match and incremental_score_match:
        base_content_score = max(
            0, min(100, int(effective_content_match.group("score")))
        )
        incremental_score = max(
            0, min(100, int(incremental_score_match.group("score")))
        )
        negative_emotion = (
            _clean(negative_emotion_match.group("value"))
            if negative_emotion_match
            else "低"
        )
        antagonism = (
            _clean(antagonism_match.group("value")) if antagonism_match else "无"
        )
        content_score, emotion_penalty = apply_emotion_calibration(
            base_content_score, negative_emotion, antagonism
        )
        derived = recommendation_for_scores(content_score, incremental_score)
        content_reason = (
            _clean(content_reason_match.group("value")) if content_reason_match else ""
        )
        incremental_reason = (
            _clean(incremental_reason_match.group("value"))
            if incremental_reason_match
            else ""
        )
        overall_reason = (
            _clean(overall_reason_match.group("value")) if overall_reason_match else ""
        )
        emotion_reason = (
            _clean(emotion_reason_match.group("value")) if emotion_reason_match else ""
        )
        return {
            "score": content_score,
            "base_content_score": base_content_score,
            "content_score": content_score,
            "incremental_score": incremental_score,
            "emotion_penalty": emotion_penalty,
            "negative_emotion": negative_emotion,
            "antagonism": antagonism,
            "is_dual_score": True,
            "content_type": (
                _clean(content_type_match.group("value"))
                if content_type_match
                else "未分类"
            ),
            **derived,
            "advertising": (
                _clean(advertising_match.group("value"))
                if advertising_match
                else "未评估"
            ),
            "content_reason": content_reason,
            "incremental_reason": incremental_reason,
            "overall_reason": overall_reason,
            "emotion_reason": emotion_reason,
            "scoring_reason": content_reason,
            "recommendation_reason": overall_reason or incremental_reason,
            "reason": overall_reason,
        }

    score_match = _SCORE_RE.search(body)
    if not score_match:
        return None

    score = max(0, min(100, int(score_match.group("score"))))
    grade_match = _GRADE_RE.search(body)
    parsed_grade = (
        (grade_match.group("value") if grade_match else score_match.group("grade")) or ""
    ).upper()
    grade = parsed_grade if parsed_grade in {"S", "A", "B", "C"} else grade_for_score(score)
    # Score is authoritative when the model emits an inconsistent grade.
    if grade != grade_for_score(score):
        grade = grade_for_score(score)

    reason_match = _REASON_RE.search(body)
    scoring_reason_match = _SCORING_REASON_RE.search(body)
    recommendation_reason_match = _RECOMMENDATION_REASON_RE.search(body)
    derived = _legacy_result_for_grade(grade)
    legacy_reason = _clean(reason_match.group("value")) if reason_match else ""
    return {
        "score": score,
        "base_content_score": None,
        "content_score": None,
        "incremental_score": None,
        "emotion_penalty": 0,
        "negative_emotion": "未评估",
        "antagonism": "未评估",
        "is_dual_score": False,
        "content_type": "未分类",
        "grade": grade,
        **derived,
        "advertising": (
            _clean(advertising_match.group("value")) if advertising_match else "未评估"
        ),
        "scoring_reason": (
            _clean(scoring_reason_match.group("value"))
            if scoring_reason_match
            else legacy_reason
        ),
        "recommendation_reason": (
            _clean(recommendation_reason_match.group("value"))
            if recommendation_reason_match
            else legacy_reason
        ),
        "content_reason": "",
        "incremental_reason": "",
        "overall_reason": "",
        "emotion_reason": "",
        "reason": legacy_reason,
    }


def format_recommendation_section(parsed: dict[str, Any]) -> str:
    """Render a parsed recommendation with all derived fields normalized."""
    if parsed.get("is_dual_score"):
        return "\n".join(
            [
                "# 推荐指数",
                f"**内容结论**：{parsed['verdict']}",
                f"**推荐等级**：{parsed['grade']}",
                f"**内容类型**：{parsed['content_type']}",
                f"**基础内容价值分**：{parsed['base_content_score']}/100",
                f"**内容价值分**：{parsed['content_score']}/100",
                f"**原片增量分**：{parsed['incremental_score']}/100",
                f"**负面情绪风险**：{parsed['negative_emotion']}",
                f"**对立煽动判断**：{parsed['antagonism']}",
                f"**情绪校准扣分**：{parsed['emotion_penalty']}分",
                f"**观看建议**：{parsed['advice']}",
                f"**广告判断**：{parsed['advertising']}",
                f"**内容价值依据**：{parsed['content_reason'] or '未提供'}",
                f"**原片增量依据**：{parsed['incremental_reason'] or '未提供'}",
                f"**情绪风险依据**：{parsed['emotion_reason'] or '未提供'}",
                f"**综合判断**：{parsed['overall_reason'] or '未提供'}",
            ]
        )
    return "\n".join(
        [
            "# 推荐指数",
            f"**内容结论**：{parsed['verdict']}",
            f"**推荐等级**：{parsed['grade']}",
            f"**推荐分数**：{parsed['score']}/100",
            f"**观看建议**：{parsed['advice']}",
            f"**广告判断**：{parsed['advertising']}",
            f"**打分依据**：{parsed['scoring_reason'] or '未提供'}",
            f"**推荐理由**：{parsed['recommendation_reason'] or '未提供'}",
        ]
    )


def normalize_recommendation(markdown: str) -> str:
    """Replace a recommendation block with a deterministic canonical rendering."""
    text = (markdown or "").strip()
    section_match = _SECTION_RE.search(text)
    parsed = parse_recommendation(text)
    if not section_match or not parsed:
        return text
    canonical = format_recommendation_section(parsed)
    before = text[: section_match.start()].strip()
    after = text[section_match.end() :].strip()
    parts = [part for part in (before, canonical, after) if part]
    return "\n\n".join(parts)


def remove_recommendation(markdown: str) -> str:
    """Remove an existing recommendation block before asking for a fresh evaluation."""
    return _SECTION_RE.sub("", (markdown or "").strip(), count=1).strip()


def replace_recommendation(markdown: str, recommendation_section: str) -> str:
    """Prepend or replace the recommendation section in a polished article."""
    article = (markdown or "").strip()
    section_text = (recommendation_section or "").strip()
    section_match = _SECTION_RE.search(section_text)
    if not section_match or not parse_recommendation(section_text):
        raise ValueError("推荐评估章节格式无效")

    normalized_section = format_recommendation_section(
        parse_recommendation(section_text) or {}
    )
    article_without_old = _SECTION_RE.sub("", article, count=1).strip()
    if not article_without_old:
        return normalized_section
    return f"{normalized_section}\n\n{article_without_old}"
