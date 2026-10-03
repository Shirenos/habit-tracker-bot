from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router(name="basic")

HELP_TEXT = (
    "<b>Commands</b>\n"
    "/add &lt;habit&gt; — create a habit\n"
    "/list — show your habits\n"
    "/done &lt;id&gt; — mark a habit done today\n"
    "/stats — streaks and the last 7 days\n"
    "/delete &lt;id&gt; — delete a habit\n"
    "/remind HH:MM — daily reminder (24h); <code>/remind off</code> disables it\n"
    "/help — this message"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    name = message.from_user.first_name if message.from_user else "there"
    await message.answer(
        f"👋 Hi, {name}! I help you build habits and keep your streaks alive.\n\n"
        "Start with <code>/add Drink water</code>, then mark it with /done.\n\n" + HELP_TEXT
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)
