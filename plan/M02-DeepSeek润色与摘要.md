# M02 — DeepSeek 润色与摘要

> 技术依据：见 `plan/技术方案.md` §4。

## 目标

转写文本 → 纠错/简体/分段/3～5 条一级目录 + **核心观点摘要**（Markdown）。

## 实现要点

1. `prompts.py`：从现 `full_prompt` 抽取任务指令，追加摘要小节要求。
2. `deepseek_client.polish_and_summarize(raw_text) -> str`，`openai` SDK + `.env`。
3. `temperature=0.3`，超时 120s。

## 验收

| # | 操作 | 通过标准 |
| --- | --- | --- |
| 1 | 短文本试调用 | 返回含「核心观点摘要」 |
| 2 | 错误 Key | 可读异常，供 M05 回退 |

## 完成标志

- [x] 可被主程序 import
