from aiogram import F, Router
from aiogram.types import Message

from habit_bot import keyboards as kb
from habit_bot import texts

router = Router(name="fallback")


@router.message(F.text)
async def unknown_text(message: Message) -> None:
    """Anything we did not recognise: a friendly hint plus the menu keyboard."""
    await message.answer(texts.unknown(), reply_markup=kb.main_menu())
