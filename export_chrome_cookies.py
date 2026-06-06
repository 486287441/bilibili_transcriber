"""Export Chrome cookies via CDP (works while Chrome is running)."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import config

_CHROME_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    / "Google"
    / "Chrome"
    / "Application"
    / "chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    / "Google"
    / "Chrome"
    / "Application"
    / "chrome.exe",
)
_DEBUG_PORT = int(os.getenv("CHROME_DEBUG_PORT", "9222"))
_YOUTUBE_HINTS = ("youtube.com", "youtu.be", "google.com")


def _chrome_exe() -> Path | None:
    for candidate in _CHROME_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def _fetch_json(url: str) -> object:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ensure_chrome_debugging(url: str = "https://www.youtube.com/") -> None:
    try:
        _fetch_json(f"http://127.0.0.1:{_DEBUG_PORT}/json/version")
        return
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        pass

    chrome = _chrome_exe()
    if not chrome:
        raise RuntimeError("未找到 Chrome 安装路径。")

    subprocess.Popen(
        [
            str(chrome),
            f"--remote-debugging-port={_DEBUG_PORT}",
            "--new-window",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )

    for _ in range(20):
        time.sleep(0.5)
        try:
            _fetch_json(f"http://127.0.0.1:{_DEBUG_PORT}/json/version")
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            continue
    raise RuntimeError(f"Chrome 远程调试端口 {_DEBUG_PORT} 未就绪。")


def _pick_target(targets: list[dict]) -> dict:
    for target in targets:
        if target.get("type") == "page" and "youtube.com" in (target.get("url") or ""):
            return target
    for target in targets:
        if target.get("type") == "page":
            return target
    raise RuntimeError("未找到可用的 Chrome 页面目标。")


def _cdp_get_all_cookies(ws_url: str) -> list[dict]:
    try:
        import websocket  # type: ignore
    except ImportError as exc:
        raise RuntimeError('缺少 websocket-client，请执行: pip install websocket-client') from exc

    ws = websocket.create_connection(ws_url, timeout=15)
    try:
        ws.send(json.dumps({"id": 1, "method": "Network.enable", "params": {}}))
        _ = ws.recv()
        ws.send(json.dumps({"id": 2, "method": "Network.getAllCookies", "params": {}}))
        while True:
            payload = json.loads(ws.recv())
            if payload.get("id") == 2:
                return payload.get("result", {}).get("cookies", [])
    finally:
        ws.close()


def _matches_site(domain: str, site: str) -> bool:
    lowered = domain.lstrip(".").lower()
    if site == "youtube":
        return any(hint in lowered for hint in _YOUTUBE_HINTS)
    if site == "bilibili":
        return "bilibili.com" in lowered or "b23.tv" in lowered
    if site == "douyin":
        return "douyin.com" in lowered or "iesdouyin.com" in lowered
    return True


def _to_netscape(cookies: list[dict], *, site: str) -> str:
    lines = [
        "# Netscape HTTP Cookie File",
        "# Exported via Chrome DevTools Protocol",
        "",
    ]
    for cookie in cookies:
        domain = cookie.get("domain") or ""
        if not _matches_site(domain, site):
            continue
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        expires = str(int(cookie.get("expires", 0) or 0))
        name = cookie.get("name") or ""
        value = cookie.get("value") or ""
        path = cookie.get("path") or "/"
        lines.append(
            "\t".join([domain, include_subdomains, path, secure, expires, name, value])
        )
    return "\n".join(lines) + "\n"


def export_site_cookies(site: str, *, open_url: str | None = None) -> Path:
    """Export cookies for *site* to cookies/www.<site>_cookies.txt."""
    if site == "youtube":
        open_url = open_url or "https://www.youtube.com/"
    _ensure_chrome_debugging(open_url or "https://www.youtube.com/")

    targets = _fetch_json(f"http://127.0.0.1:{_DEBUG_PORT}/json/list")
    if not isinstance(targets, list):
        raise RuntimeError("读取 Chrome 调试目标失败。")

    target = _pick_target(targets)
    ws_url = target.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("Chrome 页面未提供 webSocketDebuggerUrl。")

    cookies = _cdp_get_all_cookies(ws_url)
    matched = [c for c in cookies if _matches_site(c.get("domain") or "", site)]
    if not matched:
        raise RuntimeError(f"未从 Chrome 读取到 {site} 相关 Cookie。")

    filename = {
        "youtube": "www.youtube.com_cookies.txt",
        "bilibili": "www.bilibili.com_cookies.txt",
        "douyin": "www.douyin.com_cookies.txt",
    }.get(site, f"www.{site}.cookies.txt")
    out_path = config.COOKIES_DIR / filename
    config.COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_to_netscape(cookies, site=site), encoding="utf-8")
    return out_path


def main() -> None:
    import sys

    site = (sys.argv[1] if len(sys.argv) > 1 else "youtube").strip().lower()
    path = export_site_cookies(site)
    print(f"已导出 {site} Cookie: {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
