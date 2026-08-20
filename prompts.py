"""Prompt templates for transcript correction, summary, and article structure."""

from __future__ import annotations


TRANSCRIPT_CORRECTION_SYSTEM = """这是语音识别生成的无标点转写稿，其中可能存在错字、同音近音误识别、漏字、多字和专有名词识别错误。

请根据上下文恢复说话人最可能的原话：

* 重新断句、添加标点并合理分段；
* 修正能够从语义、语法或上下文明确判断的语音识别错误；
* 忠实保留原意、措辞和口语风格，不进行润色或内容改写；
* 不得仅为了让句子更优美而修改文字；无法可靠判断时保留原文。

只输出校对后的完整转写稿。"""

TRUSTED_TRANSCRIPT_RULES = """## 原文
输入是已校对的可信逐字稿。正文的文字、标点和顺序必须完整保留，不再纠错、润色或改写。只在真正切换独立议题时插入 2～5 个 `##` 标题；例子、背景、数据、原因和结论留在所属议题内。新闻串讲可按独立新闻分章。"""

VIDEO_SUMMARY_RULES = """## 视频总结
- 先写 `**一句话主旨**：...`，直接说明核心结论。
- 再写 `**核心内容**：`，列 3～8 条 `- **短标题**：结论或事实 + 必要依据、数据、案例或影响`。
- 删除口头填充与重复，保留关键专名、步骤、数字、边界和不确定性；区分事实、原作者观点与推测。
- 只依据逐字稿，不补充外部事实；篇幅服从信息密度。"""

LANGUAGE_RULES = """## 语言
若逐字稿主要不是简体中文，先完整准确地译为简体中文；保留专名、术语和原意，必要时附原文。最终三个章节均使用简体中文。"""

TOC_RULES = """## 目录
只列「原文」中的 `##` 标题，格式为 `- [章节标题](#章节标题)`；链接文字必须与标题完全一致。"""

ORIGINAL_RULES = TRUSTED_TRANSCRIPT_RULES

OUTPUT_STRUCTURE = """## 输出契约
只输出最终 Markdown，一级标题严格按以下顺序且不得增加：
`# 视频总结`、`# 目录`、`# 原文`。"""

POLISH_PROMPT_TEMPLATE = f"""你是中文视频转写整理助手。输入已经完成保守纠错；请只做总结和章节整理。

{OUTPUT_STRUCTURE}

{LANGUAGE_RULES}

{VIDEO_SUMMARY_RULES}

{TOC_RULES}

{ORIGINAL_RULES}

通用要求：只依据逐字稿，不编造，不输出思考过程或元说明。"""

def render_polish_system(prompt_template: str) -> str:
    """Render strict-mode instructions and migrate retired saved templates."""
    template = (prompt_template or "").strip()
    legacy_start = "**步骤 B — 纠错与整理**"
    next_section = "**步骤 C — 章节划分原则**"
    start = template.find(legacy_start)
    end = template.find(next_section, start + len(legacy_start)) if start >= 0 else -1
    if start >= 0 and end > start:
        template = template[:start] + TRUSTED_TRANSCRIPT_RULES + template[end:]
    template = template.replace(
        "翻译完成后再做纠错、分段与润色。",
        "翻译完成后再做总结与章节整理。",
    )
    template = template.replace("{{recommendation_criteria}}", "")
    template = template.replace(
        "`# 推荐指数`、`# 视频总结`、`# 目录`、`# 原文`",
        "`# 视频总结`、`# 目录`、`# 原文`",
    )
    template = template.replace("请只做评价、总结和章节整理", "请只做总结和章节整理")
    return template.strip()


POLISH_AND_SUMMARY_SYSTEM = render_polish_system(POLISH_PROMPT_TEMPLATE)
ORIGINAL_SECTION_USER_HINT = "按系统规则处理以下可信逐字稿。"


def build_polish_user_message(raw_text: str) -> str:
    return f"{ORIGINAL_SECTION_USER_HINT}\n\n{raw_text.strip()}"


FOLLOWUP_SYSTEM = """你是文章阅读助手。用户会提供一篇整理后的视频文稿（含目录与原文），随后就文章内容提问。

要求：
- 只根据提供的文稿回答，不要编造文稿没有的信息。
- 若文稿无法回答某个问题，明确说明。
- 用简洁清晰的中文作答。"""


def build_followup_article_message(article_text: str) -> str:
    return f"### 文章正文 ###\n{article_text.strip()}"


def build_doubao_prompt(raw_text: str) -> str:
    """Build the clipboard fallback prompt using the selected polish mode."""
    from server.settings_store import get_polish_prompt_template

    system_prompt = render_polish_system(get_polish_prompt_template())
    return (
        "### 任务指令 ###\n"
        "请严格按下列规则直接输出最终 Markdown，不要输出思考过程：\n\n"
        f"{system_prompt}\n\n"
        f"{build_polish_user_message(raw_text.strip())}\n\n---"
    )
