"""Map raw task errors to brief user-facing summaries."""

from __future__ import annotations

import re

_KNOWN_BRIEF = {
    "转写失败",
    "下载音频失败",
    "本地音频文件不存在",
    "找不到已存转写文本",
    "发布失败（已执行回退流程）",
}


def summarize_task_error(message: str | None) -> str | None:
    if not message:
        return None
    msg = message.strip()
    if not msg:
        return None
    if msg in _KNOWN_BRIEF:
        return msg

    lower = msg.lower()

    if "412" in msg or "precondition failed" in lower:
        return "B站 Cookie 失效，请重新导出"
    if "403" in msg or "sign in" in lower or "please log in" in lower:
        return "需要登录或无权访问"

    if "unexpected_eof" in lower or ("ssl" in lower and "eof" in lower):
        return "下载时网络连接中断"
    if "timed out" in lower or "timeout" in lower or "10060" in msg:
        return "网络超时"
    if "connection reset" in lower or "connection aborted" in lower:
        return "网络连接被重置"
    if "416" in msg or "range not satisfiable" in lower:
        return "下载缓存损坏，正在重试"
    if "winerror 32" in lower or "being used by another process" in lower:
        return "下载文件被占用，请重试"
    if "errno 22" in lower or "[errno 22]" in lower:
        return "下载异常，请重试"

    if "unable to download" in lower or "[download] got error" in lower:
        if "412" in msg:
            return "B站 Cookie 失效，请重新导出"
        if "ssl" in lower or "unexpected_eof" in lower:
            return "下载时网络连接中断"
        if "errno 22" in lower:
            return "下载异常，请重试"
        return "视频下载失败"

    if "is not defined" in lower or "nameerror" in lower:
        return "程序内部错误"
    if "deepseek" in lower and ("auth" in lower or "401" in msg or "403" in msg):
        return "DeepSeek 鉴权失败"
    if "feishu" in lower or "lark" in lower:
        return "飞书发布失败"

    if msg.startswith("ERROR:"):
        return summarize_task_error(msg[6:].strip())

    cleaned = re.sub(r"^\[download\]\s*", "", msg, flags=re.I).strip()
    if cleaned != msg and len(cleaned) <= 48:
        return summarize_task_error(cleaned) or cleaned

    if len(msg) <= 32:
        return msg
    return msg[:28].rstrip() + "…"
