import pytest
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, User

from conftest import ADMIN_ID, last
from habit_bot import texts
from habit_bot.config import ConfigError, parse_admin_ids
from habit_bot.handlers.admin import IsAdmin
from habit_bot.storage import AdminStats


def make_message(user_id: int | None) -> Message:
    from datetime import UTC, datetime

    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="x") if user_id is not None else None,
        text="/admin",
    )


async def test_is_admin_filter():
    flt = IsAdmin()
    ids = frozenset({ADMIN_ID, 5})
    assert await flt(make_message(ADMIN_ID), admin_ids=ids) is True
    assert await flt(make_message(5), admin_ids=ids) is True
    assert await flt(make_message(6), admin_ids=ids) is False
    assert await flt(make_message(None), admin_ids=ids) is False  # e.g. channel post
    assert await flt(make_message(ADMIN_ID)) is False  # no admins configured: nobody passes
    assert await flt(make_message(ADMIN_ID), admin_ids=frozenset()) is False


def test_parse_admin_ids():
    assert parse_admin_ids("") == frozenset()
    assert parse_admin_ids("  ") == frozenset()
    assert parse_admin_ids("1") == frozenset({1})
    assert parse_admin_ids(" 1, 22 ,,333 ,1") == frozenset({1, 22, 333})


@pytest.mark.parametrize("raw", ["abc", "1,two", "1;2", "12.5"])
def test_parse_admin_ids_rejects_garbage(raw):
    with pytest.raises(ConfigError, match="ADMIN_IDS"):
        parse_admin_ids(raw)


def test_load_settings_reads_admin_ids(monkeypatch, tmp_path):
    from habit_bot.config import load_settings

    monkeypatch.setenv("BOT_TOKEN", "dummy-test-token")
    monkeypatch.setenv("ADMIN_IDS", "10, 20")
    assert load_settings(tmp_path / "missing.env").admin_ids == frozenset({10, 20})
    monkeypatch.delenv("ADMIN_IDS")
    assert load_settings(tmp_path / "missing.env").admin_ids == frozenset()


async def test_admin_sees_stats(chat, admin_chat, service):
    await chat.say("/add Читать")
    await chat.say("/done 1")
    reply = last(await admin_chat.say("/admin"), SendMessage)
    assert "Админ-панель" in reply.text
    assert "Пользователей: <b>1</b>" in reply.text
    assert "Активных за 7 дней: <b>1</b>" in reply.text
    assert "Привычек: <b>1</b>" in reply.text
    assert "Отметок сегодня: <b>1</b>" in reply.text
    assert "Размер БД" in reply.text


async def test_non_admin_is_ignored_silently(chat):
    assert await chat.say("/admin") == []  # no reply at all, not even the "unknown" hint


async def test_admin_command_is_not_advertised(chat):
    helptext = last(await chat.say("/help"), SendMessage).text
    assert "/admin" not in helptext


def test_format_size():
    assert texts.format_size(0) == "0 B"
    assert texts.format_size(1023) == "1023 B"
    assert texts.format_size(1536) == "1.5 KB"
    assert texts.format_size(5 * 1024 * 1024) == "5.0 MB"
    assert texts.format_size(3 * 1024**3) == "3.0 GB"
    assert texts.format_size(2048 * 1024**3) == "2048.0 GB"


def test_admin_panel_text():
    text = texts.admin_panel(AdminStats(10, 4, 25, 7, 2048))
    for expected in ("10", "4", "25", "7", "2.0 KB"):
        assert f"<b>{expected}</b>" in text
