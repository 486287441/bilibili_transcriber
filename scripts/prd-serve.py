#!/usr/bin/env python3
"""Preview for PRD page: serve ASCII dir; mirror choices.json to 对话 html/."""
from __future__ import annotations

import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
MIRROR = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else None


class PrdHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/save-choices":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400, "Invalid JSON")
            return
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        primary = ROOT / "choices.json"
        primary.write_text(text, encoding="utf-8")
        if MIRROR:
            MIRROR.mkdir(parents=True, exist_ok=True)
            (MIRROR / "choices.json").write_text(text, encoding="utf-8")
        body = json.dumps({"ok": True, "path": str(primary)}, ensure_ascii=False).encode(
            "utf-8"
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        if args and str(args[0]).startswith("POST /api/save-choices"):
            sys.stderr.write("PRD: saved choices.json\n")


def main() -> None:
    os.chdir(ROOT)
    server = HTTPServer(("127.0.0.1", PORT), PrdHandler)
    print(f"PRD preview: http://127.0.0.1:{PORT}", flush=True)
    print(f"Serving: {ROOT}", flush=True)
    if MIRROR:
        print(f"Mirror choices: {MIRROR / 'choices.json'}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: prd-serve.py <serve_dir> [port] [mirror_dir]", file=sys.stderr)
        sys.exit(2)
    main()
