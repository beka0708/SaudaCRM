"""Конфигурация Telegram-бота (aiogram).

Bot создаётся в команде runbot (после проверки токена), а Dispatcher — здесь,
чтобы роутеры/хендлеры могли его импортировать. FSM хранится в памяти процесса
(для прототипа достаточно; при перезапуске бота незавершённые диалоги сбросятся).
"""
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from decouple import config

BOT_TOKEN = config("BOT_TOKEN", default="")

dp = Dispatcher(storage=MemoryStorage())
