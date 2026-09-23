"""Общие хендлеры: /start, /cancel."""
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import main_menu

router = Router()


@router.message(CommandStart())
async def start(message: Message, employee):
    name = employee.get_full_name() or employee.username
    await message.answer(
        f"Привет, {name}! 👋\nВыберите действие в меню ниже.",
        reply_markup=main_menu(),
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu())
