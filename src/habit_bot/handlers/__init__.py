from aiogram import Router

from habit_bot.handlers import basic, fallback, habits, reminders
from habit_bot.handlers.middleware import ResetStateMiddleware


def build_router() -> Router:
    """Combine all feature routers into one (the catch-all fallback goes last)."""
    router = Router(name="root")
    router.message.outer_middleware(ResetStateMiddleware())
    router.include_router(basic.router)
    router.include_router(habits.router)
    router.include_router(reminders.router)
    router.include_router(fallback.router)
    return router


__all__ = ["build_router"]
