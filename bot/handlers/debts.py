"""Сценарий «Оплата долга»: должник → сумма → погашение (FIFO) → приход в кассу.

Погашение делает apps.debts.services.add_payment (гасит долги от старых к новым),
а приход в кассу — DebtPayment.save(). ORM обёрнут в sync_to_async.
"""
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async

from apps.analytics.services import money
from aiogram.types import InlineKeyboardButton
from bot.keyboards import BTN_DEBT, CB_OTHER, main_menu, pairs_kb
from bot.queries import find_clients as _find_clients
from bot.states import DebtPaymentFSM

router = Router()


@sync_to_async
def _get_debtors():
    from apps.clients.models import Client

    result = []
    for c in Client.objects.filter(is_active=True):
        debt = c.current_debt
        if debt > 0:
            # Коротко: в три столбца длинная подпись не помещается,
            # точную сумму бот покажет на следующем шаге.
            result.append((c.id, c.name))
    return result


@sync_to_async
def _get_client_debt(cid):
    from apps.clients.models import Client

    return Client.objects.get(pk=cid).current_debt


@sync_to_async
def _finalize_payment(client_id, amount):
    from apps.clients.models import Client
    from apps.debts.services import add_payment
    from apps.finance.services import get_cash_balance

    client = Client.objects.get(pk=client_id)
    payments = add_payment(client, amount, comment="Оплата долга (бот)")
    applied = sum((p.amount for p in payments), Decimal("0"))
    return {
        "client": client.name,
        "applied": applied,
        "debt": client.current_debt,
        "balance": get_cash_balance(),
    }


def _debtors_kb(debtors):
    # Три столбца: должников десятки, одним списком занимают весь экран.
    return pairs_kb(
        debtors, "pay_client", columns=3,
        extra=[InlineKeyboardButton(text="✏️ Другой клиент",
                                    callback_data=f"pay_client:{CB_OTHER}")],
    )


@router.message(F.text == BTN_DEBT)
async def debt_start(message: Message, state: FSMContext):
    debtors = await _get_debtors()
    await state.clear()
    await state.set_state(DebtPaymentFSM.client)
    await message.answer(
        "Кто оплачивает долг?" if debtors
        else "Среди активных клиентов должников нет. Впишите имя для поиска:",
        reply_markup=_debtors_kb(debtors))


@router.callback_query(DebtPaymentFSM.client, F.data == f"pay_client:{CB_OTHER}")
async def debt_client_other(cb: CallbackQuery, state: FSMContext):
    await state.set_state(DebtPaymentFSM.find_client)
    await cb.message.edit_text("Напишите имя клиента (можно часть):")
    await cb.answer()


@router.message(DebtPaymentFSM.find_client)
async def debt_client_find(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Введите имя:")
        return
    found = await _find_clients(text)
    if not found:
        await message.answer(
            f"Клиент «{text}» не найден. Попробуйте другое написание "
            f"или часть имени:")
        return
    await state.set_state(DebtPaymentFSM.client)
    await message.answer(
        f"Нашёл {len(found)} — выберите:",
        reply_markup=pairs_kb(found, "pay_client", columns=3))


@router.callback_query(DebtPaymentFSM.client, F.data.startswith("pay_client:"))
async def debt_client(cb: CallbackQuery, state: FSMContext):
    cid = int(cb.data.split(":")[1])
    debt = await _get_client_debt(cid)
    await state.update_data(client_id=cid)
    await state.set_state(DebtPaymentFSM.amount)
    await cb.message.edit_text(
        f"Текущий долг: <b>{money(debt)} сом</b>\n\nВведите сумму оплаты:"
    )
    await cb.answer()


@router.message(DebtPaymentFSM.amount)
async def debt_amount(message: Message, state: FSMContext):
    raw = (message.text or "").replace(",", ".").strip()
    try:
        amount = Decimal(raw)
    except (InvalidOperation, TypeError):
        amount = None
    if amount is None or amount <= 0:
        await message.answer("Нужно положительное число. Ещё раз:")
        return

    data = await state.get_data()
    result = await _finalize_payment(data["client_id"], str(amount))
    await state.clear()

    msg = (
        f"✅ Оплата принята: <b>{money(result['applied'])} сом</b>\n\n"
        f"Остаток долга ({result['client']}): <b>{money(result['debt'])} сом</b>\n"
        f"💰 Касса: <b>{money(result['balance'])} сом</b>"
    )
    if result["applied"] < amount:
        msg += "\n\n⚠️ Сумма больше долга — лишнее не учтено."
    await message.answer(msg, reply_markup=main_menu())
