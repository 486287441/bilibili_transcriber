"""Prompt templates for DeepSeek polish/summary and Doubao clipboard fallback."""

from __future__ import annotations

import math

# Doubao fallback: lighter instructions (manual paste workflow).
TASK_INSTRUCTIONS_LEGACY = """精准纠错：仅修正原文中明显的同音、近音错别字，不改动原文语义；
字体统一：全文转换为规范简体中文；
内容保真：完整保留原文所有信息与原意，严禁增删、改写、补充任何内容；
合理分段：依据原文语义逻辑做适度自然段划分。"""

VIDEO_SUMMARY_RULES = """## 「视频总结」写法（# 视频总结 章节内）

先识别视频整体结构类型（教程 / 访谈 / 演讲 / 讨论，只选最贴切的一种），再按类型侧重提炼，不要把所有内容平等对待。

必须仔细阅读逐字稿，去除口语冗余（如「那个」「就是说」「嗯」「对对对」等填充词与明显重复），识别核心主题、主要论点与关键结论；忠实反映原文立场，不添加原文没有的观点；专有名词、数据、重要案例须准确保留。

区分核心论点与支撑细节：总结里写论点与结论，细节只保留最关键者。

输出格式（严格按此顺序，使用 Markdown）：
1. **一句话主旨**：单独一段，概括全片核心。
2. **核心内容**：用 `- ` 列表分条写出要点（3～8 条为宜），条目标题可加粗；教程偏重步骤/方法，访谈偏重观点碰撞，演讲偏重论点链，讨论偏重议题与立场。
3. **结论或建议**（若原文有）：单独一小节 `### 结论与建议`，否则省略。

禁止在本章节写目录或大段逐字原文。"""

TOC_RULES = """## 「目录」写法（# 目录 章节内）

- 只列「原文」中的 ## 二级标题，每条一行。
- **必须可点击跳转**：使用 Markdown 锚点链接，格式固定为 `- [章节标题](#章节标题)`。
- 「章节标题」必须与下文「原文」中对应 `## ` 标题文字**完全一致**（字符一致，才能跳转）。
- 不要写一级标题 # 视频总结 / # 目录 / # 原文 自身。
- 根据视频类型组织目录用语：教程用步骤感，访谈用话题感，演讲用论点感，讨论用议题感。"""

ORIGINAL_RULES = """## 「原文」写法（# 原文 章节内）

**步骤 A — 识别类型**（在心里完成，可在第一段用一句括注类型，如「（类型：教程）」）  
判断视频属于：教程 / 访谈 / 演讲 / 讨论，后续分段侧重须匹配该类型。

**步骤 B — 书面化整理**  
- 纠错、繁转简、去口语填充词与明显重复表达。  
- 不删事实、不改立场、不编造。  
- 按语义分段，段落清晰。

**步骤 C — 章节数量（按用户消息中的「建议小节数」执行，不得明显偏离）**  
- 转写 ≤1500 字：恰好 **3** 个 `##` 小节。  
- 转写 >1500 字：**3 + ceil((字数 - 1500) / 500)** 个 `##` 小节。  

**步骤 D — 划分侧重（因类型而异）**  
| 类型 | 分段侧重 |
| --- | --- |
| 教程 | 步骤、操作、模块、由浅入深 |
| 访谈 | 话题块、问答轮次、观点转折 |
| 演讲 | 论点递进、篇章、高潮与总结 |
| 讨论 | 议题切换、观点异同、争议点 |

每个小节：`## 章节标题` + 正文若干段。不要在本章节末尾再写「核心观点摘要」（总结只在 # 视频总结）。"""

OUTPUT_STRUCTURE = """## 输出结构（必须严格遵守）

全文只输出以下三个一级标题章节，**顺序固定**，不要增加其它一级章节，不要用代码块包裹全文：

```
# 视频总结
（按 VIDEO_SUMMARY_RULES）

# 目录
（按 TOC_RULES）

# 原文
（按 ORIGINAL_RULES）
```"""

POLISH_AND_SUMMARY_SYSTEM = f"""你是中文视频转写整理助手。根据用户提供的转写逐字稿，直接输出最终 Markdown。

{OUTPUT_STRUCTURE}

{VIDEO_SUMMARY_RULES}

{TOC_RULES}

{ORIGINAL_RULES}

通用要求：
- 使用 Markdown；章节之间空一行。
- 不要输出思考过程或元说明。
- 不要编造原文不存在的事实。"""


def suggested_section_count(char_count: int) -> int:
    """Section count for # 原文 per product rules."""
    if char_count <= 1500:
        return 3
    return 3 + math.ceil((char_count - 1500) / 500)


def build_polish_user_message(raw_text: str) -> str:
    text = raw_text.strip()
    n = len(text)
    sections = suggested_section_count(n)
    return f"""### 转写统计 ###
字数（字符数）：{n}
建议「原文」小节数：{sections}

### 转文字结果 ###
{text}"""


def build_doubao_prompt(raw_text: str) -> str:
    """Clipboard prompt for Doubao fallback."""
    text = raw_text.strip()
    sections = suggested_section_count(len(text))
    return f"""### 任务指令 ###
请把下方转写整理为三部分 Markdown：# 视频总结、# 目录（带可跳转锚点链接）、# 原文（约 {sections} 个小节）。
{TASK_INSTRUCTIONS_LEGACY}

### 转写统计 ###
字数：{len(text)}

### 转文字结果 ###
{text}

---"""
