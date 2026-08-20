"""Post-transcription publish pipeline: DeepSeek → Feishu, with Doubao fallback."""

from __future__ import annotations

import os
import webbrowser
from datetime import datetime
from pathlib import Path

import pyperclip

from deepseek_client import DeepSeekError, correct_transcript, organize_transcript
from feishu_client import FeishuError, create_video_document
from prompts import build_doubao_prompt
from server.settings_store import is_second_stage_enabled

DOUBAO_URL = "https://www.doubao.com/"
_PROJECT_ROOT = Path(__file__).resolve().parent
_LAST_TRANSCRIPT_PATH = _PROJECT_ROOT / "downloads" / "last_transcript.txt"


class PipelineCancelled(RuntimeError):
    pass


def _check_cancelled(cancelled) -> None:
    if cancelled is not None and cancelled():
        raise PipelineCancelled("任务已取消")


def _cleanup_cancelled_outputs(task_id: str) -> None:
    for path in (
        _PROJECT_ROOT / "downloads" / "transcripts" / f"{task_id}.txt",
        _PROJECT_ROOT / "downloads" / "polished" / f"{task_id}.md",
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def backup_transcript(raw_text: str) -> Path:
    """Save latest raw transcript before cloud publish (M05)."""
    _LAST_TRANSCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LAST_TRANSCRIPT_PATH.write_text(raw_text.strip() + "\n", encoding="utf-8")
    return _LAST_TRANSCRIPT_PATH


def open_feishu_in_browser(doc_url: str) -> None:
    """Open the Feishu document in the system default browser (new tab when supported)."""
    url = (doc_url or "").strip()
    if not url:
        return
    print("[浏览器] 正在打开飞书文档...")
    try:
        webbrowser.open(url, new=2)
    except Exception as exc:
        print(f"[浏览器] 自动打开失败: {exc}\n   请手动访问: {url}")


def postprocess_and_publish(
    raw_text: str,
    *,
    title: str,
    url: str,
    input_is_trusted: bool = False,
    task_id: str | None = None,
) -> tuple[str, str, str]:
    """Run the strict DeepSeek flow and create one Feishu doc per video."""
    body_md, trusted_text = postprocess_article(
        raw_text,
        task_id=task_id,
        input_is_trusted=input_is_trusted,
    )
    print("[飞书] 创建视频文档...")
    doc_url = create_video_document(
        title=title,
        url=url,
        transcribed_at=datetime.now(),
        body_md=body_md,
    )
    return doc_url, body_md, trusted_text


def postprocess_article(
    raw_text: str,
    *,
    input_is_trusted: bool = False,
    task_id: str | None = None,
    cancelled=None,
) -> tuple[str, str]:
    """Generate the final Markdown locally without waiting for Feishu."""
    if input_is_trusted:
        trusted_text = raw_text.strip()
    else:
        print("\n[DeepSeek] 断句、标点与保守纠错中...")
        trusted_text = correct_transcript(raw_text)
    _check_cancelled(cancelled)
    if task_id:
        transcript_path = _PROJECT_ROOT / "downloads" / "transcripts" / f"{task_id}.txt"
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(trusted_text.strip() + "\n", encoding="utf-8")

    if is_second_stage_enabled():
        print("[DeepSeek] 生成总结、目录与章节中...")
        body_md = organize_transcript(trusted_text)
    else:
        print("[DeepSeek] 第二阶段已关闭，直接使用第一阶段结果。")
        body_md = trusted_text
    _check_cancelled(cancelled)
    return body_md, trusted_text


def generate_local_article_result(
    raw_text: str,
    *,
    task_id: str,
    input_is_trusted: bool = False,
    cancelled=None,
) -> bool:
    """Generate and persist Markdown; publishing is intentionally out of band."""
    _check_cancelled(cancelled)
    backup_transcript(raw_text)
    try:
        body_md, _trusted_text = postprocess_article(
            raw_text,
            task_id=task_id,
            input_is_trusted=input_is_trusted,
            cancelled=cancelled,
        )
    except PipelineCancelled:
        _cleanup_cancelled_outputs(task_id)
        return False
    except DeepSeekError as exc:
        if cancelled is not None and cancelled():
            _cleanup_cancelled_outputs(task_id)
            return False
        print(f"\n[失败] 润色失败: {exc}")
        fallback_to_doubao(raw_text)
        return False
    except Exception as exc:
        if cancelled is not None and cancelled():
            _cleanup_cancelled_outputs(task_id)
            return False
        print(f"\n[失败] 未预期错误: {exc}")
        fallback_to_doubao(raw_text)
        return False

    from server.article_store import save_polished

    _check_cancelled(cancelled)
    article_path = save_polished(task_id, body_md)
    try:
        _check_cancelled(cancelled)
    except PipelineCancelled:
        _cleanup_cancelled_outputs(task_id)
        return False
    print(f"\n[完成] 本地 Markdown 已生成:\n   {article_path}")
    return True


def fallback_to_doubao(raw_text: str) -> None:
    """Copy Doubao prompt to clipboard and open Doubao (M05)."""
    pyperclip.copy(build_doubao_prompt(raw_text))
    print("[回退] 已进入豆包模式：转写原文已复制到剪贴板。")
    print("[回退] 正在打开豆包...")
    webbrowser.open(DOUBAO_URL)


def publish_or_fallback(
    raw_text: str,
    *,
    title: str,
    url: str,
    open_browser: bool = True,
    task_id: str | None = None,
    input_is_trusted: bool = False,
) -> bool:
    """Try cloud publish; on failure run Doubao fallback. Returns True if Feishu succeeded."""
    backup_transcript(raw_text)

    try:
        doc_url, body_md, _trusted_text = postprocess_and_publish(
            raw_text,
            title=title,
            url=url,
            input_is_trusted=input_is_trusted,
            task_id=task_id,
        )
    except (DeepSeekError, FeishuError) as exc:
        print(f"\n[失败] 发布失败: {exc}")
        fallback_to_doubao(raw_text)
        return False
    except Exception as exc:
        print(f"\n[失败] 未预期错误: {exc}")
        fallback_to_doubao(raw_text)
        return False

    if task_id:
        from server.article_store import save_polished

        save_polished(task_id, body_md)

    print(f"\n[完成] 已写入飞书文档:\n   {doc_url}")
    if open_browser:
        open_feishu_in_browser(doc_url)
    return True


def publish_or_fallback_result(
    raw_text: str,
    *,
    title: str,
    url: str,
    open_browser: bool = True,
    task_id: str | None = None,
    input_is_trusted: bool = False,
) -> tuple[bool, str | None]:
    """Same flow as publish_or_fallback but also returns Feishu URL on success."""
    backup_transcript(raw_text)

    try:
        doc_url, body_md, _trusted_text = postprocess_and_publish(
            raw_text,
            title=title,
            url=url,
            input_is_trusted=input_is_trusted,
            task_id=task_id,
        )
    except (DeepSeekError, FeishuError) as exc:
        print(f"\n[失败] 发布失败: {exc}")
        fallback_to_doubao(raw_text)
        return False, None
    except Exception as exc:
        print(f"\n[失败] 未预期错误: {exc}")
        fallback_to_doubao(raw_text)
        return False, None

    if task_id:
        from server.article_store import save_polished

        save_polished(task_id, body_md)

    print(f"\n[完成] 已写入飞书文档:\n   {doc_url}")
    if open_browser:
        open_feishu_in_browser(doc_url)
    return True, doc_url
