"""Доступ к боту — только для сотрудников с привязанным telegram_id.

Middleware ищет User по telegram_id входящего пользователя. Если не нашли —
вежливо отказываем и показываем его Telegram ID (чтобы админ вписал его в
карточку сотрудника). Если нашли — кладём сотрудника в data["employee"],
и он доступен хендлерам как аргумент `employee`.
"""
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async


@sync_to_async
def _get_employee(telegram_id):
    from apps.users.models import User

    return User.objects.filter(telegram_id=telegram_id, is_active=True).first()


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return  # системные апдейты без пользователя — игнорируем

        employee = await _get_employee(tg_user.id)
        if employee is None:
            text = (
                "⛔ У вас нет доступа к боту.\n\n"
                f"Ваш Telegram ID: <code>{tg_user.id}</code>\n"
                "Передайте его администратору, чтобы он привязал ваш аккаунт."
            )
            if isinstance(event, Message):
                await event.answer(text)
            elif isinstance(event, CallbackQuery):
                await event.answer("Нет доступа", show_alert=True)
            return

        data["employee"] = employee
        return await handler(event, data)
