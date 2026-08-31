"""Запуск Telegram-бота через Django: python manage.py runbot

Бот живёт внутри Django-окружения и работает напрямую с ORM/сервисами.
"""
import asyncio

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Запустить Telegram-бота (aiogram polling)"

    def handle(self, *args, **options):
        from bot.config import BOT_TOKEN, dp

        if not BOT_TOKEN:
            raise CommandError(
                "BOT_TOKEN не задан в .env — вставьте токен бота и запустите снова."
            )

        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        from bot.handlers import common, debts, expenses, sales
        from bot.middlewares import AuthMiddleware

        # Доступ проверяем на всех сообщениях и нажатиях кнопок.
        dp.message.middleware(AuthMiddleware())
        dp.callback_query.middleware(AuthMiddleware())

        dp.include_router(common.router)
        dp.include_router(sales.router)
        dp.include_router(debts.router)
        dp.include_router(expenses.router)

        bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

        self.stdout.write(self.style.SUCCESS("Бот запущен. Останов — Ctrl+C."))
        asyncio.run(dp.start_polling(bot))
