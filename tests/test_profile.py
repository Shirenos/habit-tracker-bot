import re
from pathlib import Path

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import (
    SetChatMenuButton,
    SetMyCommands,
    SetMyDescription,
    SetMyName,
    SetMyShortDescription,
)

from conftest import FakeSession
from habit_bot import profile

ROOT = Path(__file__).resolve().parent.parent


def test_profile_texts_respect_bot_api_limits():
    assert len(profile.BOT_NAME) <= 64
    assert len(profile.SHORT_DESCRIPTION) <= 120
    assert len(profile.DESCRIPTION) <= 512
    assert profile.BOT_COMMANDS and len(profile.BOT_COMMANDS) <= 100
    for command in profile.BOT_COMMANDS:
        assert re.fullmatch(r"[a-z0-9_]{1,32}", command.command)
        assert 3 <= len(command.description) <= 256
        assert re.search(r"[А-Яа-я]", command.description), "descriptions are in Russian"


def test_command_list_covers_the_public_commands():
    names = {c.command for c in profile.BOT_COMMANDS}
    assert {"add", "done", "list", "stats", "remind", "delete", "menu"} <= names


async def test_apply_profile_calls_every_endpoint():
    from aiogram import Bot

    session = FakeSession()
    bot = Bot("123456:TEST-TOKEN", session=session)
    assert await profile.apply_profile(bot) == []
    kinds = {type(m) for _, m in session.calls}
    assert kinds == {
        SetMyName,
        SetMyDescription,
        SetMyShortDescription,
        SetMyCommands,
        SetChatMenuButton,
    }
    name = next(m for _, m in session.calls if isinstance(m, SetMyName))
    assert name.name == profile.BOT_NAME


async def test_apply_profile_reports_failures(monkeypatch, capsys):
    from aiogram import Bot

    session = FakeSession()
    bot = Bot("123456:TEST-TOKEN", session=session)
    original = session.make_request

    async def flaky(bot_, method, timeout=None):
        if isinstance(method, SetMyName):
            raise TelegramBadRequest(method, "Bad Request: rate limit")
        return await original(bot_, method, timeout)

    monkeypatch.setattr(session, "make_request", flaky)
    failures = await profile.apply_profile(bot)
    assert len(failures) == 1 and failures[0].startswith("name:")
    assert "TEST-TOKEN" not in capsys.readouterr().out


async def test_apply_commands_is_cheap():
    from aiogram import Bot

    session = FakeSession()
    await profile.apply_commands(Bot("123456:TEST-TOKEN", session=session))
    assert [type(m) for _, m in session.calls] == [SetMyCommands, SetChatMenuButton]


def test_avatar_generator_and_committed_file(tmp_path):
    pil = pytest.importorskip("PIL.Image")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "make_avatar", ROOT / "scripts" / "make_avatar.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = tmp_path / "avatar.png"
    img = module.build()
    img.save(out)
    assert img.size == (1024, 1024)
    assert len(img.resize((16, 16)).getcolors(256)) > 20  # a real gradient, not a flat fill

    committed = ROOT / "docs" / "avatar.png"
    assert committed.exists()
    with pil.open(committed) as picture:
        assert picture.size == (1024, 1024)
