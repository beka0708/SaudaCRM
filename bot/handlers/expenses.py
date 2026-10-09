"""Расходы: два сценария — компании и личные.

Разведены намеренно. Личные траты владельца уменьшают кассу, но НЕ входят
в расходы бизнеса и не уменьшают прибыль (см. analytics.operating_expenses),
поэтому смешивать их в одном списке нельзя — легко записать не туда.

Статьи («Сушняк», «Стоянка», «Шоппинг») задаёт заказчик, список лежит в
apps.finance.services. Каждая ложится на укрупнённую Category — по ней
считаются касса и прибыль, — а сама статья пишется в CashFlow.subcategory.

Шаги: статья (или «свой вариант» → текст) → сумма. Всё, запись готова.

Комментария нет ни у компанейского расхода, ни у личного: что именно
купили, уже написано в статье, а лишний шаг на самом частом сценарии
заметно замедляет ввод (решение заказчика).
"""
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async

from apps.analytics.services import money
from bot.keyboards import BTN_EXPENSE, BTN_PERSONAL, CB_OTHER, items_kb, main_menu
from bot.states import ExpenseFSM

router = Router()

CB = "exp_cat"


def _items(personal):
    from apps.finance.services import COMPANY_EXPENSE_ITEMS, PERSONAL_EXPENSE_ITEMS

    return [n for n, _ in (PERSONAL_EXPENSE_ITEMS if personal else COMPANY_EXPENSE_ITEMS)]


@sync_to_async
def _save(item, amount, personal):
    from apps.finance.services import add_expense, expense_category_for, get_cash_balance

    add_expense(
        expense_category_for(item, personal=personal),
        amount,
        # Комментарий дублировал бы статью — пишем в него саму статью, чтобы
        # в выгрузке кассы строка читалась и без колонки subcategory.
        comment="" if personal else item,
        subcategory=item,
    )
    return get_cash_balance()


async def _ask_category(message, state, personal):
    await state.clear()
    await state.update_data(personal=personal)
    await state.set_state(ExpenseFSM.category)
    title = "🧍 Личный расход" if personal else "➖ Расход компании"
    await message.answer(
        f"<b>{title}</b>\n\nНа что потратили?",
        reply_markup=items_kb(_items(personal), CB, columns=2),
    )


# --- вход ---

@router.message(F.text == BTN_EXPENSE)
async def expense_start(message: Message, state: FSMContext):
    await _ask_category(message, state, personal=False)


@router.message(F.text == BTN_PERSONAL)
async def personal_start(message: Message, state: FSMContext):
    await _ask_category(message, state, personal=True)


# --- выбор статьи ---

@router.callback_query(ExpenseFSM.category, F.data == f"{CB}:{CB_OTHER}")
async def expense_other(cb: CallbackQuery, state: FSMContext):
    await state.set_state(ExpenseFSM.custom_category)
    await cb.message.edit_text("На что потратили? Напишите своими словами:")
    await cb.answer()


@router.callback_query(ExpenseFSM.category, F.data.startswith(f"{CB}:"))
async def expense_category(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    item = _items(data["personal"])[int(cb.data.split(":")[1])]
    await state.update_data(item=item)
    await state.set_state(ExpenseFSM.amount)
    await cb.message.edit_text(f"<b>{item}</b>\n\nСколько потратили (сом)?")
    await cb.answer()


@router.message(ExpenseFSM.custom_category)
async def expense_custom(message: Message, state: FSMContext):
    item = (message.text or "").strip()
    if not item:
        await message.answer("Напишите, на что потратили:")
        return
    await state.update_data(item=item)
    await state.set_state(ExpenseFSM.amount)
    await message.answer(f"<b>{item}</b>\n\nСколько потратили (сом)?")


# --- сумма и комментарий ---

@router.message(ExpenseFSM.amount)
async def expense_amount(message: Message, state: FSMContext):
    raw = (message.text or "").replace(",", ".").strip()
    try:
        amount = Decimal(raw)
    except (InvalidOperation, TypeError):
        amount = None
    if amount is None or amount <= 0:
        await message.answer("Нужно положительное число, например 1500. Ещё раз:")
        return
    await state.update_data(amount=str(amount))
    await _finish(message, state, await state.get_data())


async def _finish(message, state, data):
    """Записать расход и показать итог. Общая концовка обоих сценариев."""
    balance = await _save(data["item"], data["amount"], data["personal"])
    await state.clear()
    kind = "Личный расход" if data["personal"] else "Расход компании"
    await message.answer(
        f"✅ {kind} записан\n\n"
        f"{data['item']}: <b>{money(data['amount'])} сом</b>\n"
        f"💰 Касса: <b>{money(balance)} сом</b>",
        reply_markup=main_menu(),
    )
