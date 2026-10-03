from aiogram import Router

from habit_bot.handlers import basic, habits, reminders


def build_router() -> Router:
    """Combine all feature routers into one."""
    router = Router(name="root")
    router.include_router(basic.router)
    router.include_router(habits.router)
    router.include_router(reminders.router)
    return router


__all__ = ["build_router"]
