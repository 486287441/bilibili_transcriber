from __future__ import annotations

import os
import time

import httpx
from httpx import HTTPStatusError

import config
from bilibili_transcriber import load_sensevoice_model, process_video_url
from video_urls import SUPPORTED_SITES_LABEL, extract_video_url

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN", "") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID", "") or "").strip()
API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
POLL_TIMEOUT_SECONDS = 50
REQUEST_TIMEOUT_SECONDS = 65.0

def _tg_post(
    client: httpx.Client,
    method: str,
    payload: dict,
    *,
    timeout: float = 30.0,
) -> dict:
    resp = client.post(f"{API_BASE}/{method}", json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API failed: {data}")
    return data


def send_message(client: httpx.Client, chat_id: int, text: str) -> None:
    _tg_post(client, "sendMessage", {"chat_id": chat_id, "text": text})


def poll_updates(client: httpx.Client, offset: int | None) -> list[dict]:
    payload = {"timeout": POLL_TIMEOUT_SECONDS, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    data = _tg_post(client, "getUpdates", payload, timeout=REQUEST_TIMEOUT_SECONDS)
    return data.get("result", [])


def clear_webhook(client: httpx.Client) -> None:
    # Long polling and webhook cannot be active simultaneously.
    _tg_post(client, "deleteWebhook", {"drop_pending_updates": False})


def _is_allowed_chat(chat_id: int) -> bool:
    if not TELEGRAM_CHAT_ID:
        return True
    return str(chat_id) == TELEGRAM_CHAT_ID


def main() -> None:
    config.validate()
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("缺少 TELEGRAM_BOT_TOKEN，请先在 .env 配置。")

    print("⏳ 正在加载 SenseVoice 模型...")
    model = load_sensevoice_model()
    print("🤖 Telegram Bot 已启动，等待消息...")

    offset: int | None = None
    # Keep system proxy behavior (supports restricted network environments).
    with httpx.Client(trust_env=True) as client:
        clear_webhook(client)
        while True:
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
                            client,
                            chat_id,
                            f"请发送支持的视频链接（{SUPPORTED_SITES_LABEL} 等）。",
                        )
                        continue

                    send_message(client, chat_id, "已收到链接，开始处理，请稍候...")
                    ok, doc_url, err = process_video_url(
                        video_url,
                        model,
                        open_browser=False,
                    )
                    if ok and doc_url:
                        send_message(client, chat_id, f"处理完成，飞书文档：\n{doc_url}")
                    else:
                        send_message(client, chat_id, f"处理失败：{err}")
            except KeyboardInterrupt:
                print("\n👋 已退出 Telegram Bot。")
                break
            except HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code == 409:
                    print("⚠️ 轮询冲突(409)：可能有另一个 Telegram Bot 进程正在运行。")
                    print("   请关闭重复的 telegram_bot.py 实例后重试。")
                else:
                    print(f"⚠️ 轮询异常: {exc}")
                time.sleep(3)
            except httpx.ReadTimeout:
                # Long polling timeout is expected sometimes; continue quietly.
                continue
            except Exception as exc:
                print(f"⚠️ 轮询异常: {exc}")
                time.sleep(3)


if __name__ == "__main__":
    main()
