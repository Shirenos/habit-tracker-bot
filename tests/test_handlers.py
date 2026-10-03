from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.filters import CommandObject

from habit_bot.handlers import habits as h


def make_message(user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, first_name="Ann"),
        chat=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
    )


def cmd(args: str | None) -> CommandObject:
    return CommandObject(prefix="/", command="x", args=args)


async def test_add_done_stats_delete_flow(service):
    msg = make_message()
    await h.cmd_add(msg, cmd("Read <b>"), service)
    assert "Read &lt;b&gt;" in msg.answer.call_args.args[0]  # HTML is escaped

    await h.cmd_done(msg, cmd("1"), service)
    assert "Streak" in msg.answer.call_args.args[0]
    await h.cmd_done(msg, cmd("1"), service)
    assert "already" in msg.answer.call_args.args[0]

    await h.cmd_stats(msg, service)
    assert "Current: 1" in msg.answer.call_args.args[0]

    await h.cmd_delete(msg, cmd("1"), service)
    assert "deleted" in msg.answer.call_args.args[0]
    await h.cmd_list(msg, service)
    assert "No habits" in msg.answer.call_args.args[0]


async def test_bad_ids_show_usage(service):
    msg = make_message()
    await h.cmd_done(msg, cmd("abc"), service)
    assert "Usage" in msg.answer.call_args.args[0]
    await h.cmd_delete(msg, cmd(None), service)
    assert "Usage" in msg.answer.call_args.args[0]
