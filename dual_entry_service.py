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
import pyperclip

import config
from bilibili_transcriber import load_sensevoice_model, process_video_url
from video_urls import SUPPORTED_SITES_LABEL, extract_video_url

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN", "") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID", "") or "").strip()
API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
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
        time.sleep(1.0)


def telegram_listener() -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("ℹ️ 未配置 TELEGRAM_BOT_TOKEN，Telegram 入口未启用。")
        return

    print("🤖 Telegram 监听已启动，等待消息...")
    offset: int | None = None
    with httpx.Client(trust_env=True) as client:
        clear_webhook(client)
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

                    task = TaskItem(source="telegram", url=video_url, chat_id=int(chat_id))
                    queue_size = enqueue_task(task)
                    if is_processing():
                        send_message(
                            int(chat_id),
                            f"已收到链接，当前正在处理其他任务，已加入队列(前面约 {max(queue_size - 1, 0)} 个)。",
                        )
                    else:
                        send_message(int(chat_id), "已收到链接，马上开始处理。")
            except Exception as exc:
                print(f"⚠️ Telegram 轮询异常: {exc}")
                time.sleep(3)


def worker(model) -> None:
    while not stop_event.is_set():
        try:
            task = task_queue.get(timeout=0.5)
        except Empty:
            continue

        with processing_lock:
            _append_queue_log("started", task, queue_size=task_queue.qsize())
            print(f"\n🚀 开始处理 [{task.source}] {task.url}")
            if task.source == "telegram" and task.chat_id is not None:
                send_message(task.chat_id, "开始处理你的链接，请稍候...")
            ok, doc_url, err = process_video_url(
                task.url,
                model,
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
            _append_queue_log("finished", task, queue_size=task_queue.qsize())
            task_queue.task_done()

            pending = task_queue.qsize()
            if pending > 0:
                print(f"⏭️ 当前任务结束，立刻开始下一条（队列剩余: {pending}）")
            else:
                print("👀 当前无排队任务，继续监听中...")


def main() -> None:
    config.validate()
    print("⏳ 正在加载 SenseVoice 模型（仅加载一次）...")
    model = load_sensevoice_model()
    print("✅ 模型加载完成，双入口服务启动。")

    listener_threads = [
        threading.Thread(target=clipboard_listener, daemon=True),
        threading.Thread(target=telegram_listener, daemon=True),
    ]
    for t in listener_threads:
        t.start()

    try:
        worker(model)
    except KeyboardInterrupt:
        print("\n👋 正在退出服务...")
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
