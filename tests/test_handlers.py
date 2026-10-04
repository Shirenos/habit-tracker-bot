from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from conftest import last
from habit_bot import keyboards as kb


def buttons(markup: InlineKeyboardMarkup) -> list[tuple[str, str]]:
    return [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]


async def test_start_greets_and_shows_persistent_menu(chat):
    calls = await chat.say("/start")
    msg = last(calls, SendMessage)
    assert "Привет, Аня" in msg.text
    assert isinstance(msg.reply_markup, ReplyKeyboardMarkup)
    assert msg.reply_markup.is_persistent
    labels = [b.text for row in msg.reply_markup.keyboard for b in row]
    assert labels == list(kb.MENU_BUTTONS)


async def test_menu_and_help(chat):
    menu = last(await chat.say("/menu"), SendMessage)
    assert isinstance(menu.reply_markup, ReplyKeyboardMarkup)
    helptext = last(await chat.say("/help"), SendMessage).text
    for command in ("/add", "/done", "/list", "/stats", "/remind", "/delete", "/menu"):
        assert command in helptext


async def test_empty_states_are_friendly(chat):
    for text in ("/list", "/today", "/stats", kb.BTN_LIST, kb.BTN_STATS):
        msg = last(await chat.say(text), SendMessage)
        assert "/add" in msg.text, text
        assert msg.reply_markup.inline_keyboard[0][0].callback_data == "add"


async def test_add_escapes_html_and_rejects_duplicates(chat):
    msg = last(await chat.say("/add Read <b>20</b> pages"), SendMessage)
    assert "Привычка добавлена" in msg.text
    assert "Read &lt;b&gt;20&lt;/b&gt; pages" in msg.text and "<b>20</b>" not in msg.text
    again = last(await chat.say("/add Read <b>20</b> pages"), SendMessage)
    assert "уже есть" in again.text


async def test_add_dialog_via_button_and_cancel(chat, service):
    prompt = last(await chat.say(kb.BTN_ADD), SendMessage)
    assert "Как её назвать" in prompt.text
    await chat.say("x" * 100)  # too long: dialog stays open
    assert await service.list_with_status(1) == []
    added = last(await chat.say("Пить воду"), SendMessage)
    assert "Привычка добавлена" in added.text
    assert [h.name for h, _ in await service.list_with_status(1)] == ["Пить воду"]

    # outside of the dialog free text is not a habit
    hint = last(await chat.say("просто текст"), SendMessage)
    assert "Не понял" in hint.text and len(await service.list_with_status(1)) == 1

    await chat.say("/add")  # no args: starts the dialog
    assert "Отменено" in last(await chat.say("/cancel"), SendMessage).text
    assert "Нечего отменять" in last(await chat.say("/cancel"), SendMessage).text


async def test_menu_button_leaves_add_dialog(chat, service):
    await chat.say(kb.BTN_ADD)
    shown = last(await chat.say(kb.BTN_LIST), SendMessage)  # not saved as a habit name
    assert "Пока нет привычек" in shown.text
    assert await service.list_with_status(1) == []


async def test_done_command_flow(chat, service):
    await chat.say("/add Читать")
    done = last(await chat.say("/done 1"), SendMessage)
    assert "выполнено" in done.text and "🔥" in done.text
    assert "уже отмечена" in last(await chat.say("/done #1"), SendMessage).text
    assert "Не нашёл" in last(await chat.say("/done 99"), SendMessage).text
    assert "/done 1" in last(await chat.say("/done abc"), SendMessage).text


async def test_done_without_id_opens_checklist(chat):
    await chat.say("/add Читать")
    msg = last(await chat.say("/done"), SendMessage)
    assert "Сегодня" in msg.text
    assert ("✅ Читать", "done:1:t") in buttons(msg.reply_markup)


async def test_today_button_marks_done_in_place(chat, service):
    await chat.say("/add Читать")
    await chat.say("/add Бегать")
    shown = last(await chat.say(kb.BTN_TODAY), SendMessage)
    assert ("✅ Бегать", "done:2:t") in buttons(shown.reply_markup)

    calls = await chat.press("done:2:t")
    edit = last(calls, EditMessageText)  # edited, not re-sent
    assert not [c for c in calls if isinstance(c, SendMessage)]
    assert "1/2" in edit.text and "✅ <b>Бегать</b>" in edit.text
    assert "done:2:t" not in [d for _, d in buttons(edit.reply_markup)]
    assert "done:1:t" in [d for _, d in buttons(edit.reply_markup)]
    assert "Серия" in last(calls, AnswerCallbackQuery).text

    toast = last(await chat.press("done:2:t", message_id=501), AnswerCallbackQuery).text
    assert "Уже отмечено" in toast
    last_done = last(await chat.press("done:1:t", message_id=502), EditMessageText)
    assert "2/2" in last_done.text and "Все привычки на сегодня выполнены" in last_done.text


async def test_list_buttons_and_unknown_habit(chat):
    await chat.say("/add Читать")
    shown = last(await chat.say("/list"), SendMessage)
    assert ("🗑", "del:1") in buttons(shown.reply_markup)
    calls = await chat.press("done:1:l")
    assert ("✔️ Читать", "noop") in buttons(last(calls, EditMessageText).reply_markup)
    gone = last(await chat.press("done:42:l"), AnswerCallbackQuery)
    assert gone.show_alert and "не найдена" in gone.text
    assert "Уже отмечено" in last(await chat.press("noop"), AnswerCallbackQuery).text


async def test_delete_requires_confirmation(chat, service):
    await chat.say("/add Читать")
    ask = last(await chat.say("/delete 1"), SendMessage)
    assert "Удалить привычку?" in ask.text
    assert len(await service.list_with_status(1)) == 1  # nothing deleted yet
    assert ("↩️ Отмена", "v:l") in buttons(ask.reply_markup)

    await chat.press("v:l")  # cancel = back to the list
    assert len(await service.list_with_status(1)) == 1

    edit = last(await chat.press("del:1"), EditMessageText)
    assert "Удалить привычку?" in edit.text
    calls = await chat.press("delok:1")
    assert "удалена" in last(calls, EditMessageText).text
    assert await service.list_with_status(1) == []
    assert "Привычка уже удалена" in last(await chat.press("delok:1"), AnswerCallbackQuery).text
    assert "Не нашёл" in last(await chat.say("/delete 1"), SendMessage).text
    assert "/delete 1" in last(await chat.say("/delete"), SendMessage).text


async def test_refresh_edits_in_place_and_is_idempotent(chat):
    await chat.say("/add Читать")
    first = await chat.press("v:l", message_id=700)
    assert last(first, EditMessageText).message_id == 700
    second = await chat.press("v:l", message_id=700)  # identical content: Telegram refuses
    assert "актуально" in last(second, AnswerCallbackQuery).text
    # unknown views are ignored quietly
    assert not [c for c in await chat.press("v:zzz") if isinstance(c, EditMessageText)]


async def test_stats_has_chart_and_streaks(chat):
    await chat.say("/add Читать")
    await chat.say("/done 1")
    text = last(await chat.say(kb.BTN_STATS), SendMessage).text
    assert "<pre>" in text and "← сегодня" in text
    assert "🔥 1 день" in text and "🏆 рекорд 1" in text


async def test_reminders_command_and_panel(chat, scheduler):
    panel = last(await chat.say(kb.BTN_REMIND), SendMessage)
    assert "выключено" in panel.text
    assert ("🕘 21:00", "rem:21:00") in buttons(panel.reply_markup)

    assert "21:30" in last(await chat.say("/remind 21:30"), SendMessage).text
    assert (await scheduler.get(1)).strftime("%H:%M") == "21:30"
    assert "ЧЧ:ММ" in last(await chat.say("/remind 99:99"), SendMessage).text

    edit = last(await chat.press("rem:08:00"), EditMessageText)
    assert "<b>08:00</b>" in edit.text and ("✔️ 08:00", "rem:08:00") in buttons(edit.reply_markup)
    assert "выключено" in last(await chat.press("rem:off"), EditMessageText).text
    assert await scheduler.get(1) is None
    assert "и так не было" in last(await chat.say("/remind off"), SendMessage).text


async def test_settings(chat):
    await chat.say("/add Читать")
    text = last(await chat.say(kb.BTN_SETTINGS), SendMessage).text
    assert "Настройки" in text and "<b>1</b> из 30" in text and "UTC" in text


async def test_callback_buttons_are_isolated_per_user(chat, service):
    await chat.say("/add Читать")
    other = type(chat)(chat.dp, chat.bot, chat.session, user_id=2)
    toast = last(await other.press("done:1:t"), AnswerCallbackQuery)
    assert toast.show_alert
    assert "Не нашёл" in last(await other.say("/delete 1"), SendMessage).text
