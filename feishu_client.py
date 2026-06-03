"""Feishu wiki: one docx per video via lark-cli (user identity)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import config
from text_stats import format_article_stats_block

_LARK_IDENTITY = "user"
_MAX_WIKI_TITLE_LEN = 100


def _lark_executable() -> str:
    for name in ("lark-cli.cmd", "lark-cli", "lark-cli.exe"):
        path = shutil.which(name)
        if path:
            return path
    raise FeishuError("未找到 lark-cli，请先安装并完成 lark-cli auth login。")


class FeishuError(Exception):
    """Readable failure for logging and M05 fallback."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause


@dataclass(frozen=True)
class VideoDoc:
    document_id: str
    url: str
    node_token: str | None = None


def _wiki_doc_title(video_title: str, when: datetime) -> str:
    """Date-prefixed title for sorting in the archive folder."""
    base = re.sub(r"\s+", " ", (video_title or "").strip()) or "未命名视频"
    prefix = when.strftime("%Y-%m-%d ")
    room = _MAX_WIKI_TITLE_LEN - len(prefix)
    if room < 10:
        return base[:_MAX_WIKI_TITLE_LEN]
    return prefix + base[:room]


def _parse_cli_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    decoder = json.JSONDecoder()
    idx = 0
    last: dict[str, Any] | None = None
    while idx < len(text):
        start = text.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, start)
            if isinstance(obj, dict):
                last = obj
            idx = end
        except json.JSONDecodeError:
            idx = start + 1
    if last is None:
        raise FeishuError(f"lark-cli 未返回 JSON：{text[:300]}")
    if not last.get("ok", True):
        err = last.get("error") or {}
        msg = err.get("message") or err.get("hint") or str(err) or "未知错误"
        raise FeishuError(f"飞书 API 失败：{msg}")
    return last


def _run_lark_cli(args: list[str]) -> dict[str, Any]:
    cmd = [_lark_executable(), *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
    except FileNotFoundError as exc:
        raise FeishuError(
            "未找到 lark-cli，请先安装并完成 lark-cli auth login。",
            cause=exc,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FeishuError("lark-cli 执行超时。", cause=exc) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise FeishuError(
            f"lark-cli 退出码 {proc.returncode}"
            + (f"：{detail[:400]}" if detail else "")
        )

    return _parse_cli_json(proc.stdout)


def _create_wiki_doc_node(doc_title: str) -> VideoDoc:
    payload = _run_lark_cli(
        [
            "wiki",
            "+node-create",
            "--as",
            _LARK_IDENTITY,
            "--space-id",
            config.FEISHU_WIKI_SPACE_ID,
            "--parent-node-token",
            config.FEISHU_WIKI_PARENT_NODE_TOKEN,
            "--title",
            doc_title,
        ]
    )
    data = payload.get("data") or {}
    document_id = (data.get("obj_token") or "").strip()
    if not document_id:
        raise FeishuError("创建飞书文档失败：未返回 obj_token。")

    url = (data.get("url") or "").strip()
    if not url:
        url = f"https://open.feishu.cn/docx/{document_id}"

    node_token = (data.get("node_token") or "").strip() or None
    return VideoDoc(document_id=document_id, url=url, node_token=node_token)


def _write_markdown(document_id: str, markdown: str) -> None:
    cmd = [
        _lark_executable(),
        "docs",
        "+update",
        "--api-version",
        "v2",
        "--as",
        _LARK_IDENTITY,
        "--doc",
        document_id,
        "--command",
        "append",
        "--doc-format",
        "markdown",
        "--content",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=markdown,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise FeishuError("lark-cli 执行超时。", cause=exc) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise FeishuError(
            f"lark-cli 退出码 {proc.returncode}"
            + (f"：{detail[:400]}" if detail else "")
        )
    _parse_cli_json(proc.stdout)


def create_video_document(
    title: str,
    url: str,
    transcribed_at: datetime | str,
    body_md: str,
) -> str:
    """Create a new Feishu doc for one video and write header + body. Returns doc URL."""
    if isinstance(transcribed_at, datetime):
        when = transcribed_at
        time_str = when.strftime("%Y-%m-%d %H:%M:%S")
    else:
        when = datetime.now()
        time_str = str(transcribed_at).strip()

    display_title = (title or "").strip() or "未命名视频"
    doc = _create_wiki_doc_node(_wiki_doc_title(display_title, when))

    body = body_md.strip()
    content = (
        f"# {display_title}\n\n"
        f"**标题：** {display_title}  \n"
        f"**链接：** {url.strip()}  \n"
        f"**转写时间：** {time_str}\n\n"
        f"{format_article_stats_block(body)}\n"
        f"{body}\n"
    )
    _write_markdown(doc.document_id, content)
    return doc.url
