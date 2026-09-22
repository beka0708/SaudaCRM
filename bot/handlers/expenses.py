"""Сценарий «Расход»: категория → сумма → комментарий → запись в кассу.

Всё через apps.finance.services (общая логика), ORM-вызовы обёрнуты в
sync_to_async, т.к. aiogram асинхронный, а Django ORM — синхронный.
"""
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async

from apps.analytics.services import money
from bot.keyboards import BTN_EXPENSE, categories_kb, main_menu
from bot.states import ExpenseFSM

router = Router()

CB_PREFIX = "exp_cat"


def _expense_categories_kb():
    from apps.finance.services import EXPENSE_CATEGORIES

    return categories_kb(EXPENSE_CATEGORIES, CB_PREFIX)


def _category_label(value: str) -> str:
    from apps.finance.models import CashFlow

    return CashFlow.Category(value).label


@sync_to_async
def _save_expense(category, amount, comment):
    from apps.finance.services import add_expense, get_cash_balance

    add_expense(category, amount, comment=comment)
    return get_cash_balance()


@router.message(F.text == BTN_EXPENSE)
async def expense_start(message: Message, state: FSMContext):
    await state.set_state(ExpenseFSM.category)
    await message.answer("Выберите категорию расхода:", reply_markup=_expense_categories_kb())


@router.callback_query(ExpenseFSM.category, F.data.startswith(f"{CB_PREFIX}:"))
async def expense_category(cb: CallbackQuery, state: FSMContext):
    value = cb.data.split(":", 1)[1]
    await state.update_data(category=value)
    await state.set_state(ExpenseFSM.amount)
    await cb.message.edit_text(
        f"Категория: <b>{_category_label(value)}</b>\n\nВведите сумму расхода (в сомах):"
    )
    await cb.answer()


@router.message(ExpenseFSM.amount)
async def expense_amount(message: Message, state: FSMContext):
    raw = (message.text or "").replace(",", ".").strip()
    try:
        amount = Decimal(raw)
    except (InvalidOperation, TypeError):
        amount = None
    if amount is None or amount <= 0:
        await message.answer("Нужно положительное число, например 1500. Попробуйте ещё раз:")
        return
    await state.update_data(amount=str(amount))
    await state.set_state(ExpenseFSM.comment)
    await message.answer("Комментарий (или отправьте «-», чтобы пропустить):")


@router.message(ExpenseFSM.comment)
async def expense_comment(message: Message, state: FSMContext):
    comment = (message.text or "").strip()
    if comment == "-":
        comment = ""
    data = await state.get_data()
    balance = await _save_expense(data["category"], data["amount"], comment)
    await state.clear()
    await message.answer(
        f"✅ Расход записан: <b>{money(data['amount'])} сом</b> "
        f"({_category_label(data['category'])}).\n"
        f"💰 Касса теперь: <b>{money(balance)} сом</b>",
        reply_markup=main_menu(),
    )
