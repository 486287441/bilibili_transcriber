"""Generate favicon PNG/ICO assets in web/public and sync index.html."""

from __future__ import annotations

import base64
import re
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
INDEX = ROOT / "index.html"
FAVICON_VERSION = "2"
BRAND = "#1b365d"
PAPER = "#f5f4ed"
PLAY = "#2d5a8a"

FAVICON_BLOCK_START = "    <!-- favicon:start -->"
FAVICON_BLOCK_END = "    <!-- favicon:end -->"


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    r = max(2, int(size * 0.22))
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=r, fill=BRAND)

    mx = int(size * 0.22)
    my = int(size * 0.14)
    mw = int(size * 0.56)
    mh = int(size * 0.72)
    d.rounded_rectangle((mx, my, mx + mw, my + mh), radius=max(1, int(size * 0.08)), fill=PAPER)

    bar_h = max(2, int(size * 0.07))
    gap = max(2, int(size * 0.1))
    x1 = mx + int(mw * 0.16)
    x2 = mx + int(mw * 0.84)
    y = my + int(mh * 0.22)

    for width_ratio in (1.0, 1.0, 0.68):
        x_end = int(x1 + (x2 - x1) * width_ratio)
        d.rectangle((x1, y, x_end, y + bar_h), fill=BRAND)
        y += bar_h + gap

    px = mx + int(mw * 0.18)
    py = my + int(mh * 0.72)
    ps = max(3, int(size * 0.14))
    d.polygon([(px, py), (px, py + ps), (px + int(ps * 0.92), py + ps // 2)], fill=PLAY)

    return img


def favicon_block(data_uri: str) -> str:
    v = FAVICON_VERSION
    return "\n".join(
        [
            FAVICON_BLOCK_START,
            f'    <link rel="icon" type="image/png" href="{data_uri}" />',
            f'    <link rel="shortcut icon" href="/favicon.ico?v={v}" type="image/x-icon" />',
            f'    <link rel="icon" href="/favicon.ico?v={v}" type="image/x-icon" />',
            f'    <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png?v={v}" />',
            f'    <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png?v={v}" />',
            f'    <link rel="icon" href="/favicon.svg?v={v}" type="image/svg+xml" />',
            f'    <link rel="apple-touch-icon" href="/apple-touch-icon.png?v={v}" />',
            FAVICON_BLOCK_END,
        ]
    )


def sync_index_html(data_uri: str) -> None:
    block = favicon_block(data_uri)
    text = INDEX.read_text(encoding="utf-8")
    pattern = re.compile(
        r"    <!-- favicon:start -->.*?    <!-- favicon:end -->",
        re.DOTALL,
    )
    if pattern.search(text):
        text = pattern.sub(block, text, count=1)
    else:
        text = text.replace(
            "    <title>视频转文稿助手</title>\n",
            f"    <title>视频转文稿助手</title>\n{block}\n",
            1,
        )

    orphan = re.compile(
        r"    <link rel=\"(?:shortcut icon|icon|apple-touch-icon)\"[^>]*>\n",
    )
    parts = text.split(FAVICON_BLOCK_END, 1)
    if len(parts) == 2:
        head, tail = parts
        tail = orphan.sub("", tail)
        text = head + FAVICON_BLOCK_END + tail

    INDEX.write_text(text, encoding="utf-8")


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)

    for size in (16, 32, 48):
        draw_icon(size).save(PUBLIC / f"favicon-{size}x{size}.png")

    icon32 = draw_icon(32)
    icon32.save(PUBLIC / "apple-touch-icon.png")
    icon32.save(PUBLIC / "favicon.ico", format="ICO", sizes=[(32, 32)])

    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="7" fill="#1b365d"/>
  <rect x="7" y="4.5" width="18" height="23" rx="2.5" fill="#f5f4ed"/>
  <rect x="10" y="9" width="12" height="2.2" rx="1.1" fill="#1b365d"/>
  <rect x="10" y="13" width="12" height="2.2" rx="1.1" fill="#1b365d"/>
  <rect x="10" y="17" width="8" height="2.2" rx="1.1" fill="#1b365d"/>
  <path d="M11.5 21.5v4.5l4-2.25z" fill="#2d5a8a"/>
</svg>
"""
    (PUBLIC / "favicon.svg").write_text(svg.strip() + "\n", encoding="utf-8")

    png_b64 = base64.b64encode((PUBLIC / "favicon-32x32.png").read_bytes()).decode("ascii")
    data_uri = f"data:image/png;base64,{png_b64}"
    sync_index_html(data_uri)
    print("[favicons] wrote web/public/favicon.* and synced index.html")


if __name__ == "__main__":
    main()
