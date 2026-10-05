"""Кнопка «Погашение»: гасим НАШИ долги — кредиты и долг Ашимжану.

Два сценария:
  - у кредита задан платёж по умолчанию (50 000 и 40 000) — гасится одним
    нажатием, без вопросов: суммы всегда одинаковые;
  - у долга Ашимжану суммы разные и он в ДОЛЛАРАХ — спрашиваем сумму в
    долларах и обязательный комментарий, пересчёт в сомы по фиксированному
    курсу из самого обязательства (заказчик просил курс не менять).

Деньги списываются из кассы в `ObligationPayment.save()` — единая точка,
как у прихода партии и оплаты долга клиента. При этом погашение НЕ
считается расходом бизнеса и не уменьшает прибыль: это уменьшение
обязательства, а не издержка.
"""
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async

from apps.analytics.services import money
from bot.keyboards import BTN_REPAY, main_menu
from bot.states import RepayFSM

router = Router()


@sync_to_async
def _obligations():
    from apps.finance.models import Obligation

    return [
        {
            "id": o.id, "code": o.code, "name": o.name,
            "currency": o.currency, "rate": o.rate,
            "remaining": o.remaining, "remaining_kgs": o.remaining_kgs,
            "default_payment": o.default_payment,
        }
        for o in Obligation.objects.filter(is_active=True)
    ]


@sync_to_async
def _info(oid):
    from apps.finance.models import Obligation

    o = Obligation.objects.filter(pk=oid).first()
    if not o:
        return None
    return {
        "id": o.id, "name": o.name, "currency": o.currency, "rate": o.rate,
        "remaining": o.remaining, "remaining_kgs": o.remaining_kgs,
        "default_payment": o.default_payment,
    }


@sync_to_async
def _pay(oid, amount, comment, employee):
    from apps.finance.models import Obligation, ObligationPayment
    from apps.finance.services import get_cash_balance

    o = Obligation.objects.get(pk=oid)
    amount = Decimal(str(amount))
    if amount > o.remaining:
        return {"error": f"Платёж больше остатка: осталось {o.remaining} {o.currency}."}
    ObligationPayment.objects.create(
        obligation=o, amount=amount, rate=o.rate, comment=comment
    )
    o.refresh_from_db()
    return {
        "name": o.name, "currency": o.currency, "rate": o.rate,
        "paid": amount, "paid_kgs": amount * o.rate,
        "remaining": o.remaining, "remaining_kgs": o.remaining_kgs,
        "balance": get_cash_balance(),
    }


def _result_text(r):
    lines = [f"✅ <b>{r['name']}</b> — погашено\n"]
    if r["currency"] == "USD":
        lines.append(f"Внесено: <b>{money(r['paid'])} $</b> "
                     f"({money(r['paid_kgs'])} сом по курсу {r['rate']})")
        lines.append(f"Остаток долга в долларах:\n<b>{money(r['remaining'])} $</b>")
        lines.append(f"Остаток долга в сомах:\n<b>{money(r['remaining_kgs'])} сом</b>")
        lines.append(f"Курс доллара: {r['rate']}")
    else:
        lines.append(f"Внесено: <b>{money(r['paid'])} сом</b>")
        lines.append(f"Остаток долга: <b>{money(r['remaining'])} сом</b>")
    lines.append(f"\n💰 Касса: <b>{money(r['balance'])} сом</b>")
    return "\n".join(lines)


# --- шаги ---

@router.message(F.text == BTN_REPAY)
async def repay_start(message: Message, state: FSMContext):
    await state.clear()
    obligations = await _obligations()
    if not obligations:
        await message.answer("Долгов и кредитов нет.", reply_markup=main_menu())
        return

    rows, lines = [], ["🏦 <b>Наши долги</b>\n"]
    for o in obligations:
        if o["currency"] == "USD":
            lines.append(f"{o['name']} — <b>{money(o['remaining'])} $</b> "
                         f"({money(o['remaining_kgs'])} сом)")
        else:
            lines.append(f"{o['name']} — <b>{money(o['remaining'])} сом</b>")
        # В подписи кнопки — только название: суммы уже перечислены выше.
        rows.append([InlineKeyboardButton(
            text=o["name"], callback_data=f"repay:{o['id']}")])

    lines.append("\nЧто гасим?")
    await state.set_state(RepayFSM.choose)
    await message.answer("\n".join(lines),
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(RepayFSM.choose, F.data.startswith("repay:"))
async def repay_pick(cb: CallbackQuery, state: FSMContext, employee):
    info = await _info(int(cb.data.split(":")[1]))
    if not info:
        await state.clear()
        await cb.message.edit_text("Долг не найден.")
        await cb.answer()
        return

    await state.update_data(oid=info["id"], currency=info["currency"],
                            rate=str(info["rate"]), name=info["name"])

    # Кредит с фиксированным платежом — гасим сразу, без вопросов.
    if info["default_payment"]:
        result = await _pay(info["id"], info["default_payment"], "", employee)
        await state.clear()
        if result.get("error"):
            await cb.message.edit_text(f"❌ {result['error']}")
        else:
            await cb.message.edit_text(_result_text(result))
        await cb.message.answer("Готово 👍", reply_markup=main_menu())
        await cb.answer()
        return

    # Долг в валюте — спрашиваем сумму.
    unit = "долларах" if info["currency"] == "USD" else "сомах"
    await state.set_state(RepayFSM.amount)
    await cb.message.edit_text(
        f"<b>{info['name']}</b>\n"
        f"Остаток: {money(info['remaining'])} "
        f"{'$' if info['currency'] == 'USD' else 'сом'}\n\n"
        f"Сколько вносим (в {unit})?"
    )
    await cb.answer()


@router.message(RepayFSM.amount)
async def repay_amount(message: Message, state: FSMContext):
    raw = (message.text or "").replace(",", ".").strip()
    try:
        amount = Decimal(raw)
    except (InvalidOperation, TypeError):
        amount = None
    if amount is None or amount <= 0:
        await message.answer("Нужно положительное число, например 500. Ещё раз:")
        return
    await state.update_data(amount=str(amount))
    await state.set_state(RepayFSM.comment)
    # Комментарий обязателен: по просьбе заказчика, чтобы потом было понятно,
    # за что именно платили.
    await message.answer("Комментарий (обязательно) — за что платёж?")


@router.message(RepayFSM.comment)
async def repay_comment(message: Message, state: FSMContext, employee):
    comment = (message.text or "").strip()
    if not comment or comment == "-":
        await message.answer("Комментарий обязателен. Напишите, за что платёж:")
        return
    data = await state.get_data()
    result = await _pay(data["oid"], data["amount"], comment, employee)
    await state.clear()
    if result.get("error"):
        await message.answer(f"❌ {result['error']}", reply_markup=main_menu())
        return
    await message.answer(_result_text(result), reply_markup=main_menu())
