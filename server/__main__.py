"""Entry point: python -m server"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    from server.win_subprocess import patch_subprocess_no_window

    patch_subprocess_no_window()

import errno

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _port_in_use(host: str, port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return True
    return False


def main() -> None:
    import config

    config.validate()

    import uvicorn

    from server.app import app

    host = config.SERVER_HOST
    port = config.SERVER_PORT

    if host != "127.0.0.1":
        print(
            f"警告：Phase 1 仅支持本机访问，当前 SERVER_HOST={host}，将强制绑定 127.0.0.1。",
            file=sys.stderr,
        )
        host = "127.0.0.1"

    if _port_in_use(host, port):
        print(
            f"端口 {port} 已被占用，无法启动服务。"
            f"请停止占用该端口的进程，或在 .env 中设置 SERVER_PORT 为其他端口。",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, 10048) or "address already in use" in str(exc).lower():
            print(
                f"端口 {port} 已被占用，无法启动服务。"
                f"请停止占用该端口的进程，或在 .env 中设置 SERVER_PORT 为其他端口。",
                file=sys.stderr,
            )
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
