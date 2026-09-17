"""Сценарий «Отменить операцию» (сторно из бота).

Три тапа: Отменить → выбрать из списка последних → подтвердить. Номер
документа помнить не надо — бот сам показывает, что было сделано недавно.

Отмена НЕОБРАТИМА (сторно нельзя «отсторнировать»), поэтому шаг подтверждения
оставлен и на нём прямо написано, что именно изменится. Саму работу делают
сервисы `sales/warehouse/debts.services.reverse_*` — здесь только диалог.
"""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from asgiref.sync import sync_to_async

from bot.keyboards import BTN_UNDO, main_menu
from bot.states import ReversalFSM

router = Router()

# Что изменится при отмене — показываем до подтверждения, чтобы не было сюрпризов.
_EFFECT = {
    "sale": "Товар вернётся на склад, деньги/долг откатятся.",
    "batch": "Партия уйдёт со склада, деньги за закупку вернутся в кассу.",
    "payment": "Деньги уйдут из кассы, долг клиента снова станет открытым.",
}


_LABEL_MAX = 58  # длинная подпись в Telegram обрезается/переносится некрасиво


def _button_label(op) -> str:
    """Короткая подпись кнопки. Детали (клиент и пр.) — на экране подтверждения."""
    label = f"{op['icon']} {op['title']} · {op['detail']} · {op['when']}"
    if len(label) <= _LABEL_MAX:
        return label
    # Режем середину — «что» и «когда» важнее подробностей.
    keep = _LABEL_MAX - len(op["when"]) - 6
    return f"{label[:keep].rstrip(' ·')}… · {op['when']}"


# --- обёртки над ORM/сервисами ---

@sync_to_async
def _recent_ops():
    from apps.core.services import humanize_dt, recent_operations

    return [
        {**op, "when": humanize_dt(op["dt"]), "dt": None}  # dt наружу не носим
        for op in recent_operations()
    ]


@sync_to_async
def _describe(kind, pk):
    """Краткое описание операции для экрана подтверждения."""
    from apps.analytics.services import money
    from apps.catalog.services import pack_label
    from apps.debts.models import DebtPayment
    from apps.sales.models import Sale
    from apps.warehouse.models import Batch

    if kind == "sale":
        s = Sale.objects.select_related("client").filter(pk=pk).first()
        if not s or s.is_reversed:
            return None
        who = f" · {s.client.name}" if s.client_id else ""
        return f"🧾 Продажа #{s.pk} — {money(s.total)} сом ({s.get_payment_type_display()}){who}"
    if kind == "batch":
        b = Batch.objects.select_related("product").filter(pk=pk).first()
        if not b or b.is_reversed:
            return None
        packs = b.packs_received
        return (
            f"📥 Приход — {b.product.name}, {packs} "
            f"{pack_label(b.product.pack_name, packs)}"
        )
    p = DebtPayment.objects.select_related("debt__client").filter(pk=pk).first()
    if not p or p.is_reversed:
        return None
    return f"💰 Оплата — {p.debt.client.name}, {money(p.amount)} сом"


@sync_to_async
def _reverse(kind, pk, employee):
    """Выполнить сторно и собрать отчёт о том, что изменилось."""
    from django.core.exceptions import ValidationError

    from apps.analytics.services import money
    from apps.catalog.services import pack_label
    from apps.debts.models import DebtPayment
    from apps.debts.services import reverse_debt_payment
    from apps.finance.services import get_cash_balance
    from apps.sales.models import Sale
    from apps.sales.services import reverse_sale
    from apps.warehouse.models import Batch
    from apps.warehouse.services import reverse_batch

    def stock_line(product, delta_packs, sign="+"):
        left = product.stock
        return (
            f"📦 {product.name}: {sign}{delta_packs} "
            f"{pack_label(product.pack_name, delta_packs)} "
            f"(остаток {left} {pack_label(product.pack_name, left)})"
        )

    try:
        if kind == "sale":
            sale = Sale.objects.select_related("client").get(pk=pk)
            reverse_sale(sale, user=employee, reason="Отмена из бота")
            lines = [f"✅ Продажа #{pk} отменена."]
            for item in sale.items.select_related("product"):
                lines.append(stock_line(item.product, item.packs))
            if sale.client_id:
                debt = sale.client.current_debt
                lines.append(f"👤 Долг {sale.client.name}: {money(debt)} сом")

        elif kind == "batch":
            batch = Batch.objects.select_related("product").get(pk=pk)
            packs = batch.packs_received
            reverse_batch(batch, user=employee, reason="Отмена из бота")
            lines = [
                f"✅ Приход отменён: {batch.product.name}",
                stock_line(batch.product, packs, sign="−"),
            ]

        else:
            payment = DebtPayment.objects.select_related("debt__client").get(pk=pk)
            reverse_debt_payment(payment, user=employee, reason="Отмена из бота")
            client = payment.debt.client
            lines = [
                f"✅ Оплата отменена: {client.name}, {money(payment.amount)} сом",
                f"👤 Долг снова: {money(client.current_debt)} сом",
            ]

        lines.append(f"💰 Касса: <b>{money(get_cash_balance())}</b> сом")
        return {"text": "\n".join(lines)}

    except ValidationError as exc:
        return {"error": "; ".join(exc.messages)}


# --- шаги ---

@router.message(F.text == BTN_UNDO)
async def undo_start(message: Message, state: FSMContext):
    await state.clear()
    ops = await _recent_ops()
    if not ops:
        await message.answer("Отменять пока нечего — операций нет.", reply_markup=main_menu())
        return

    rows = [
        [InlineKeyboardButton(
            text=_button_label(op),
            callback_data=f"undo:{op['kind']}:{op['id']}",
        )]
        for op in ops
    ]
    # Отдельный callback, а не "undo:cancel": иначе он попадал бы под общий
    # префикс undo: и разбор на три части падал бы.
    rows.append([InlineKeyboardButton(text="✖️ Закрыть", callback_data="undo_close")])
    await state.set_state(ReversalFSM.choose)
    await message.answer(
        "Что отменить? Последние операции:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(ReversalFSM.choose, F.data == "undo_close")
async def undo_close(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Отмена закрыта — ничего не изменилось.")
    await cb.answer()


@router.callback_query(ReversalFSM.choose, F.data.startswith("undo:"))
async def undo_pick(cb: CallbackQuery, state: FSMContext):
    _, kind, pk = cb.data.split(":")
    description = await _describe(kind, int(pk))
    if description is None:
        await state.clear()
        await cb.message.edit_text("Эта операция уже отменена или не найдена.")
        await cb.message.answer("Меню:", reply_markup=main_menu())
        await cb.answer()
        return

    await state.update_data(kind=kind, pk=int(pk))
    await state.set_state(ReversalFSM.confirm)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, отменить", callback_data="undo_ok:yes"),
        InlineKeyboardButton(text="❌ Нет", callback_data="undo_ok:no"),
    ]])
    await cb.message.edit_text(
        f"{description}\n\n{_EFFECT[kind]}\n\nОтменить эту операцию?",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(ReversalFSM.confirm, F.data == "undo_ok:yes")
async def undo_confirm(cb: CallbackQuery, state: FSMContext, employee):
    data = await state.get_data()
    result = await _reverse(data["kind"], data["pk"], employee)
    await state.clear()

    if result.get("error"):
        # Напр. по продаже уже принята оплата — подсказываем, что сделать сначала.
        await cb.message.edit_text(f"❌ Не удалось отменить.\n{result['error']}")
        await cb.message.answer("Меню:", reply_markup=main_menu())
        await cb.answer()
        return

    await cb.message.edit_text(result["text"])
    await cb.message.answer("Готово 👍", reply_markup=main_menu())
    await cb.answer()


@router.callback_query(ReversalFSM.confirm, F.data == "undo_ok:no")
async def undo_decline(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Ничего не отменили.")
    await cb.message.answer("Меню:", reply_markup=main_menu())
    await cb.answer()
