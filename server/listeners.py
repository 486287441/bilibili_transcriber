"""Clipboard background listener."""

from __future__ import annotations

import logging
import threading
import time
from ctypes import windll

import pyperclip

from server.entry_points import pending_count, submit_url
from server.runtime import is_processing
from server.settings_store import load_settings
from video_urls import extract_video_url

logger = logging.getLogger("server.listeners")


def _clipboard_sequence_number() -> int | None:
    """Return the Windows clipboard change counter when available."""
    try:
        return int(windll.user32.GetClipboardSequenceNumber())
    except (AttributeError, OSError):
        return None


class ListenerManager:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._clipboard_lock = threading.Lock()
        self._ignored_clipboard_sequence: int | None = None

    def ignore_current_clipboard_once(self, url: str) -> bool:
        """Consume only the clipboard event that produced the deleted task.

        Copying the same URL again increments the Windows clipboard sequence,
        so the next explicit copy remains eligible for submission.
        """
        sequence = _clipboard_sequence_number()
        if sequence is None:
            return False
        try:
            current_url = extract_video_url(pyperclip.paste().strip())
        except Exception:
            return False
        if not current_url or current_url != extract_video_url(url):
            return False
        with self._clipboard_lock:
            self._ignored_clipboard_sequence = sequence
        logger.info("删除任务时已忽略当前剪贴板事件 sequence=%d", sequence)
        return True

    def _is_ignored_clipboard_sequence(self, sequence: int | None) -> bool:
        if sequence is None:
            return False
        with self._clipboard_lock:
            if self._ignored_clipboard_sequence != sequence:
                return False
            self._ignored_clipboard_sequence = None
            return True

    def start(self) -> None:
        if self._threads:
            return
        self._stop_event.clear()
        self._threads.append(self._start_isolated("clipboard-listener", self._clipboard_loop))
        logger.info("剪贴板监听已启动")

    def stop(self) -> None:
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=5.0)
        self._threads.clear()

    def _start_isolated(self, name: str, target) -> threading.Thread:
        thread = threading.Thread(
            target=self._run_isolated,
            args=(name, target),
            name=name,
            daemon=True,
        )
        thread.start()
        return thread

    def _run_isolated(self, name: str, listener) -> None:
        while not self._stop_event.is_set():
            try:
                listener()
                return
            except Exception:
                logger.exception("[%s] 线程异常，5 秒后自动恢复", name)
                time.sleep(5.0)

    def _clipboard_loop(self) -> None:
        last_clip = ""
        last_sequence: int | None = None
        while not self._stop_event.is_set():
            try:
                settings = load_settings()
                if not settings.clipboard_enabled:
                    time.sleep(1.0)
                    continue

                try:
                    clip_text = pyperclip.paste().strip()
                except Exception:
                    clip_text = ""

                sequence = _clipboard_sequence_number()
                changed = (
                    sequence != last_sequence
                    if sequence is not None
                    else clip_text != last_clip
                )
                if changed:
                    last_sequence = sequence
                    last_clip = clip_text
                    if self._is_ignored_clipboard_sequence(sequence):
                        logger.debug("当前剪贴板事件已由删除操作消费 sequence=%s", sequence)
                        time.sleep(1.0)
                        continue
                    video_url = extract_video_url(clip_text)
                    if video_url:
                        result = submit_url(
                            video_url,
                            source="clipboard",
                            silent_duplicate=True,
                            emit_clipboard_detected=True,
                        )
                        if result.skipped_history:
                            logger.debug(
                                "剪贴板链接已在历史记录中，已忽略 url=%s history_id=%s",
                                video_url,
                                result.existing_id,
                            )
                        elif result.task:
                            ahead = max(pending_count() - 1, 0)
                            if is_processing():
                                logger.info(
                                    "剪贴板入队 url=%s 排队中(前面约 %d)",
                                    video_url,
                                    ahead,
                                )
                            else:
                                logger.info("剪贴板入队 url=%s", video_url)
                    elif clip_text:
                        logger.debug("剪贴板非视频链接，已忽略")
            except Exception:
                logger.exception("剪贴板监听异常（将继续运行）")
            time.sleep(1.0)


listener_manager = ListenerManager()
