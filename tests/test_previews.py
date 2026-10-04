"""The preview generator must keep working with the bot's real templates (no Chrome needed)."""

from __future__ import annotations

import importlib.util
import sys
from html import escape
from pathlib import Path

from habit_bot import keyboards, texts

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_previews.py"


def load():
    spec = importlib.util.spec_from_file_location("make_previews", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_demo_page_uses_real_templates():
    mp = load()
    stats = mp.demo_stats()
    assert len(stats) == 4
    assert [s.done_today for s in stats] == [True, False, True, False]
    body = texts.stats_view(stats, mp.TODAY)
    html = mp.page(
        [mp.Msg(body, buttons=mp.buttons(keyboards.stats_kb()))],
        mp.menu(),
    )
    assert "Статистика" in html
    assert escape(mp.CAPTION) in html
    assert "<!doctype html>" in html
