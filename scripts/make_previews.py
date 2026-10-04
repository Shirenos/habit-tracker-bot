"""Render the interface previews in ``docs/`` (chat mockups, NOT real screenshots).

The message texts and inline keyboards are produced by the bot's own code
(``habit_bot.texts`` / ``habit_bot.keyboards``) from hard-coded DEMO data, laid out as a
Telegram-like dark chat in HTML/CSS and screenshotted with headless Chrome/Chromium.
No Telegram account, network access, bot token or real chat is involved.

Usage (needs Chrome or Chromium on PATH; override with ``CHROME=/path/to/chrome``)::

    python scripts/make_previews.py
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from habit_bot import keyboards, texts  # noqa: E402
from habit_bot.db import Habit  # noqa: E402
from habit_bot.services.habits import HabitStats  # noqa: E402

DOCS = ROOT / "docs"
BOT_TITLE = "Habit Tracker"
BOT_USERNAME = "@Shirenos_Habit_Bot"
CAPTION = "Interface preview · mockup rendered from the bot's real message templates · demo data"
TODAY = date(2026, 10, 4)  # a Sunday
SCALE = 2
WIDTH = 460

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:#0b141d}
body{width:__W__px;font-family:'Roboto','Noto Sans','DejaVu Sans',sans-serif;color:#f5f5f5;
 -webkit-font-smoothing:antialiased}
.phone{background:#0e1621;background-image:
 radial-gradient(circle at 20% 10%,#14202e 0,#0e1621 55%);
 min-height:100vh;display:flex;flex-direction:column}
.top{display:flex;align-items:center;gap:12px;padding:10px 16px;background:#17212b;
 border-bottom:1px solid #0e1621}
.top img{width:42px;height:42px;border-radius:50%}
.top .t{font-size:16.5px;font-weight:500}
.top .s{font-size:13px;color:#6d7f8f;margin-top:1px}
.chat{padding:14px 12px 10px;display:flex;flex-direction:column;gap:6px;flex:1}
.row{display:flex;flex-direction:column;max-width:92%}
.row.out{align-self:flex-end;align-items:flex-end}
.row.in{align-self:flex-start;align-items:flex-start}
.bubble{border-radius:14px;padding:7px 11px 6px;font-size:15.5px;line-height:1.38;
 white-space:pre-wrap;word-break:break-word;position:relative}
.in .bubble{background:#182533;border-bottom-left-radius:5px}
.out .bubble{background:#2b5278;border-bottom-right-radius:5px}
.bubble a{color:#6ab3f3;text-decoration:none}
.bubble code{font-family:'Roboto Mono','DejaVu Sans Mono',monospace;font-size:14px;color:#8fd0ff}
.bubble pre{font-family:'Roboto Mono','DejaVu Sans Mono',monospace;font-size:13.5px;
 background:#0f1a26;border-radius:6px;padding:6px 9px;margin:3px 0;white-space:pre;
 color:#cfe7ff;display:block;overflow:hidden}
.bubble pre code{font-size:inherit;color:inherit}
.time{float:right;margin:7px 0 -2px 12px;font-size:11.5px;color:#7e92a5;line-height:1}
.out .time{color:#9fc0e0}
.kb{display:flex;flex-direction:column;gap:3px;margin-top:3px;width:100%}
.kbrow{display:flex;gap:3px}
.kbtn{flex:1;background:rgba(36,54,74,.92);border-radius:8px;padding:8px 6px;text-align:center;
 font-size:14px;font-weight:500;color:#e8f1fa;white-space:nowrap;overflow:hidden;
 text-overflow:ellipsis}
.reply{background:#17212b;padding:7px 8px 8px;display:flex;flex-direction:column;gap:5px;
 border-top:1px solid #0e1621}
.reply .rrow{display:flex;gap:5px}
.reply .rbtn{flex:1;background:#2b3a4a;border-radius:8px;padding:9px 4px;text-align:center;
 font-size:14.5px;color:#f0f4f8}
.input{background:#17212b;padding:2px 14px 10px;font-size:14px;color:#5d6f80;
 display:flex;justify-content:space-between}
.cap{background:#0b141d;color:#6d7f8f;font-size:11px;text-align:center;padding:7px 10px;
 letter-spacing:.2px}
""".replace("__W__", str(WIDTH))


@dataclass
class Msg:
    html: str
    out: bool = False
    stamp: str = ""
    buttons: list[list[str]] | None = None


def avatar_uri() -> str:
    data = base64.b64encode((DOCS / "avatar.png").read_bytes()).decode()
    return f"data:image/png;base64,{data}"


def page(messages: list[Msg], menu: list[list[str]]) -> str:
    chat = []
    for m in messages:
        kb = ""
        if m.buttons:
            rows = "".join(
                '<div class="kbrow">'
                + "".join(f'<div class="kbtn">{escape(b)}</div>' for b in r)
                + "</div>"
                for r in m.buttons
            )
            kb = f'<div class="kb">{rows}</div>'
        side = "out" if m.out else "in"
        chat.append(
            f'<div class="row {side}"><div class="bubble">{m.html}'
            f'<span class="time">{m.stamp}</span></div>{kb}</div>'
        )
    reply = "".join(
        '<div class="rrow">' + "".join(f'<div class="rbtn">{escape(b)}</div>' for b in r) + "</div>"
        for r in menu
    )
    return (
        f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head><body>"
        f'<div class="phone"><div class="top"><img src="{avatar_uri()}"><div>'
        f'<div class="t">{BOT_TITLE}</div><div class="s">бот · {BOT_USERNAME}</div></div></div>'
        f'<div class="chat">{"".join(chat)}</div><div class="reply">{reply}</div>'
        f'<div class="cap">{escape(CAPTION)}</div></div>'
        '<div id="h" style="display:none"></div>'
        "<script>document.getElementById('h').textContent="
        "document.querySelector('.phone').scrollHeight;</script></body></html>"
    )


def find_chrome() -> str:
    for candidate in (
        os.environ.get("CHROME"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ):
        if candidate:
            return candidate
    raise SystemExit("Chrome/Chromium not found; set CHROME=/path/to/chrome")


def render(html: str, out: Path) -> None:
    chrome = find_chrome()
    base = [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars"]
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "page.html"
        src.write_text(html, encoding="utf-8")
        dom = subprocess.run(
            [
                *base,
                f"--window-size={WIDTH},900",
                "--virtual-time-budget=2000",
                "--dump-dom",
                src.as_uri(),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        height = int(re.search(r'id="h"[^>]*>(\d+)<', dom).group(1)) + 1
        # Headless Chrome occasionally leaves a raster glitch in tall pages, so render until
        # two consecutive screenshots are byte-identical.
        previous = b""
        for _ in range(6):
            subprocess.run(
                [
                    *base,
                    f"--window-size={WIDTH},{height}",
                    f"--force-device-scale-factor={SCALE}",
                    "--virtual-time-budget=2000",
                    f"--screenshot={out}",
                    src.as_uri(),
                ],
                check=True,
                capture_output=True,
            )
            current = out.read_bytes()
            if current == previous:
                return
            previous = current
        raise SystemExit(f"unstable rendering of {out.name}")


# --- DEMO data --------------------------------------------------------------------------------


def demo_stats() -> list[HabitStats]:
    """Four invented habits; ``week`` ends with TODAY (Sunday)."""
    days = [TODAY - timedelta(days=6 - i) for i in range(7)]
    spec = [
        ("Пить воду", [1, 1, 0, 1, 1, 1, 1], 4, 4, 10),
        ("Читать 20 минут", [0, 0, 0, 1, 1, 1, 0], 3, 3, 3),
        ("Зарядка", [0, 1, 1, 0, 0, 1, 1], 2, 2, 5),
        ("Медитация", [0, 0, 0, 0, 0, 0, 0], 0, 0, 0),
    ]
    return [
        HabitStats(
            habit=Habit(id=i, user_id=0, name=name),
            current=cur,
            longest=best,
            total=total,
            week=list(zip(days, map(bool, flags), strict=True)),
        )
        for i, (name, flags, cur, best, total) in enumerate(spec, start=1)
    ]


def buttons(markup) -> list[list[str]]:
    return [[b.text for b in row] for row in markup.inline_keyboard]


def menu() -> list[list[str]]:
    return [[b.text for b in row] for row in keyboards.main_menu().keyboard]


def main() -> None:
    stats = demo_stats()
    shots = {
        "preview-list.png": ("/list", "21:14", texts.list_view(stats), keyboards.list_kb(stats)),
        "preview-stats.png": (
            "/stats",
            "21:15",
            texts.stats_view(stats, TODAY),
            keyboards.stats_kb(),
        ),
    }
    for name, (command, stamp, body, markup) in shots.items():
        messages = [
            Msg(escape(command), out=True, stamp=stamp),
            Msg(body, stamp=stamp, buttons=buttons(markup)),
        ]
        render(page(messages, menu()), DOCS / name)
        print("wrote", (DOCS / name).relative_to(ROOT))


if __name__ == "__main__":
    main()
