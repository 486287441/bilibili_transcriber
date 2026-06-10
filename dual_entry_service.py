from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue

import httpx
from httpx import ConnectTimeout, HTTPStatusError, ReadTimeout
import pyperclip

import config
from video_urls import SUPPORTED_SITES_LABEL, extract_video_url

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN", "") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID", "") or "").strip()
API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = (os.getenv(name, "") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def telegram_enabled() -> bool:
    """Enabled when a token is configured; set TELEGRAM_ENABLED=0 to disable."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    return _env_flag("TELEGRAM_ENABLED", default=True)
POLL_TIMEOUT_SECONDS = 50
REQUEST_TIMEOUT_SECONDS = 65.0
_PROJECT_ROOT = Path(__file__).resolve().parent
_QUEUE_LOG_PATH = _PROJECT_ROOT / "downloads" / "queue_events.log"

@dataclass(slots=True)
class TaskItem:
    source: str
    url: str
    chat_id: int | None = None


task_queue: Queue[TaskItem] = Queue()
processing_lock = threading.Lock()
stop_event = threading.Event()
_model_lock = threading.Lock()
_model = None


def is_processing() -> bool:
    return processing_lock.locked()


def _append_queue_log(event: str, task: TaskItem, *, queue_size: int) -> None:
    _QUEUE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        "source": task.source,
        "url": task.url,
        "chat_id": task.chat_id,
        "queue_size": queue_size,
        "busy": is_processing(),
    }
    with _QUEUE_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def enqueue_task(task: TaskItem) -> int:
    task_queue.put(task)
    queue_size = task_queue.qsize()
    _append_queue_log("queued", task, queue_size=queue_size)
    return queue_size


def _tg_post(client: httpx.Client, method: str, payload: dict, *, timeout: float = 30.0) -> dict:
    resp = client.post(f"{API_BASE}/{method}", json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API failed: {data}")
    return data


def send_message(chat_id: int, text: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        with httpx.Client(trust_env=True) as client:
            _tg_post(client, "sendMessage", {"chat_id": chat_id, "text": text})
    except Exception as exc:
        print(f"⚠️ Telegram 发消息失败: {exc}")


def poll_updates(client: httpx.Client, offset: int | None) -> list[dict]:
    payload = {"timeout": POLL_TIMEOUT_SECONDS, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    data = _tg_post(client, "getUpdates", payload, timeout=REQUEST_TIMEOUT_SECONDS)
    return data.get("result", [])


def clear_webhook(client: httpx.Client) -> None:
    _tg_post(client, "deleteWebhook", {"drop_pending_updates": False})


def _is_allowed_chat(chat_id: int) -> bool:
    if not TELEGRAM_CHAT_ID:
        return True
    return str(chat_id) == TELEGRAM_CHAT_ID


def clipboard_listener() -> None:
    print("📋 剪贴板监听已启动。")
    last_clip = ""
    while not stop_event.is_set():
        try:
            try:
                clip_text = pyperclip.paste().strip()
            except Exception:
                clip_text = ""

            if clip_text != last_clip:
                last_clip = clip_text
                video_url = extract_video_url(clip_text)
                if video_url:
                    task = TaskItem(source="clipboard", url=video_url)
                    queue_size = enqueue_task(task)
                    status = "当前在忙，已排队" if is_processing() else "已入队，准备处理"
                    print(f"📥 [Clipboard] {status} (队列长度: {queue_size})")
        except Exception as exc:
            print(f"⚠️ [Clipboard] 监听异常（将继续运行）: {exc}")
        time.sleep(1.0)


def telegram_listener() -> None:
    if not telegram_enabled():
        print("ℹ️ Telegram 入口已关闭（.env 中 TELEGRAM_ENABLED=0）。")
        return

    print("🤖 Telegram 监听已启动，等待消息...")
    offset: int | None = None

    while not stop_event.is_set():
        try:
            with httpx.Client(
                trust_env=True,
                timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=20.0),
            ) as client:
                try:
                    clear_webhook(client)
                except (ConnectTimeout, HTTPStatusError, httpx.HTTPError) as exc:
                    print(f"⚠️ Telegram 初始化超时（不影响剪贴板），5 秒后重试: {exc}")
                    time.sleep(5)
                    continue

                while not stop_event.is_set():
                    try:
                        updates = poll_updates(client, offset)
                        for update in updates:
                            offset = update["update_id"] + 1
                            msg = update.get("message") or {}
                            chat = msg.get("chat") or {}
                            chat_id = chat.get("id")
                            if not chat_id or not _is_allowed_chat(chat_id):
                                continue

                            text = msg.get("text") or ""
                            video_url = extract_video_url(text)
                            if not video_url:
                                send_message(
                                    chat_id,
                                    f"请发送支持的视频链接（{SUPPORTED_SITES_LABEL} 等）。",
                                )
                                continue

                            task = TaskItem(
                                source="telegram",
                                url=video_url,
                                chat_id=int(chat_id),
                            )
                            queue_size = enqueue_task(task)
                            if is_processing():
                                send_message(
                                    int(chat_id),
                                    f"已收到链接，当前正在处理其他任务，已加入队列(前面约 {max(queue_size - 1, 0)} 个)。",
                                )
                            else:
                                send_message(int(chat_id), "已收到链接，马上开始处理。")
                    except ReadTimeout:
                        continue
                    except HTTPStatusError as exc:
                        if exc.response is not None and exc.response.status_code == 409:
                            print("⚠️ Telegram 轮询冲突(409)：可能有另一个 Bot 进程在运行。")
                        else:
                            print(f"⚠️ Telegram 轮询异常: {exc}")
                        time.sleep(3)
                    except (ConnectTimeout, httpx.HTTPError) as exc:
                        print(f"⚠️ Telegram 连接中断（不影响剪贴板），3 秒后重连: {exc}")
                        time.sleep(3)
                        break
                    except Exception as exc:
                        print(f"⚠️ Telegram 轮询异常: {exc}")
                        time.sleep(3)
        except Exception as exc:
            print(f"⚠️ Telegram 服务异常，5 秒后重试: {exc}")
            time.sleep(5)


def _run_isolated_listener(name: str, listener) -> None:
    """Keep one entry alive; failures must not take down sibling listeners."""
    while not stop_event.is_set():
        try:
            listener()
            return
        except Exception as exc:
            print(f"⚠️ [{name}] 线程异常，5 秒后自动恢复（不影响其他入口）: {exc}")
            time.sleep(5)


def _start_listener(name: str, listener) -> threading.Thread:
    thread = threading.Thread(
        target=_run_isolated_listener,
        args=(name, listener),
        name=name,
        daemon=True,
    )
    thread.start()
    return thread


def get_model():
    global _model
    if _model is not None:
        return _model

    with _model_lock:
        if _model is None:
            print("⏳ 首次任务触发，正在加载 SenseVoice 模型（仅加载一次）...")
            from bilibili_transcriber import load_sensevoice_model

            _model = load_sensevoice_model()
            print("✅ SenseVoice 模型加载完成。")
    return _model


def worker() -> None:
    while not stop_event.is_set():
        try:
            task = task_queue.get(timeout=0.5)
        except Empty:
            continue

        with processing_lock:
            try:
                _append_queue_log("started", task, queue_size=task_queue.qsize())
                print(f"\n🚀 开始处理 [{task.source}] {task.url}")
                if task.source == "telegram" and task.chat_id is not None:
                    send_message(task.chat_id, "开始处理你的链接，请稍候...")
                from bilibili_transcriber import process_video_url

                ok, doc_url, err = process_video_url(
                    task.url,
                    get_model(),
                    open_browser=(task.source == "clipboard"),
                )
                if ok and doc_url:
                    print(f"✅ 处理完成: {doc_url}")
                    if task.source == "telegram" and task.chat_id is not None:
                        send_message(task.chat_id, f"处理完成，飞书文档：\n{doc_url}")
                else:
                    print(f"❌ 处理失败: {err}")
                    if task.source == "telegram" and task.chat_id is not None:
                        send_message(task.chat_id, f"处理失败：{err}")
            except Exception as exc:
                print(f"❌ 任务处理异常（队列继续运行）: {exc}")
            finally:
                _append_queue_log("finished", task, queue_size=task_queue.qsize())
                task_queue.task_done()

            pending = task_queue.qsize()
            if pending > 0:
                print(f"⏭️ 当前任务结束，立刻开始下一条（队列剩余: {pending}）")
            else:
                print("👀 当前无排队任务，继续监听中...")


def main() -> None:
    config.validate()
    print("✅ 配置检查完成，双入口服务启动。")
    print("ℹ️ SenseVoice 模型将在首次任务到来时加载，以加快启动。")

    _start_listener("clipboard-listener", clipboard_listener)
    if telegram_enabled():
        _start_listener("telegram-listener", telegram_listener)
    elif TELEGRAM_BOT_TOKEN:
        print("ℹ️ Telegram 入口已关闭（TELEGRAM_ENABLED=0），仅剪贴板在运行。")
    else:
        print("ℹ️ 未配置 TELEGRAM_BOT_TOKEN，仅剪贴板在运行。")

    try:
        worker()
    except KeyboardInterrupt:
        print("\n👋 正在退出服务...")
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
