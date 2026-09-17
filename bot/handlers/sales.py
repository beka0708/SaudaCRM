"""Сценарий «Продажа» (FSM с корзиной).

Шаги: товар → количество фасовок → цена за штуку → (ещё товар?) → тип оплаты →
клиент (для реализации) → подтверждение → провести продажу.
Продают только фасовками; цену вводит продавец (у разных клиентов разная).
Запись — через apps.sales.services.create_sale (FIFO-списание + касса/долг атомарно).
"""
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from asgiref.sync import sync_to_async

from apps.catalog.services import pack_label
from bot.keyboards import BTN_SALE, main_menu
from bot.queries import get_product_info as _get_product_info
from bot.queries import get_products as _get_products
from bot.states import SaleFSM

router = Router()


# --- обёртки над ORM/сервисами ---

@sync_to_async
def _get_clients():
    from apps.clients.models import Client

    return list(Client.objects.values_list("id", "name"))


@sync_to_async
def _finalize_sale(items, payment_type, client_id):
    from django.core.exceptions import ValidationError

    from apps.catalog.models import Product
    from apps.clients.models import Client
    from apps.finance.services import get_cash_balance
    from apps.sales.services import create_sale

    resolved = [
        {"product": Product.objects.get(pk=it["product_id"]),
         "packs": it["packs"], "price_per_unit": it["price_per_unit"]}
        for it in items
    ]
    client = Client.objects.get(pk=client_id) if client_id else None
    try:
        sale = create_sale(payment_type, resolved, client=client)
    except ValidationError as e:
        return {"error": "; ".join(e.messages)}
    return {
        "id": sale.id,
        "total": sale.total,
        "payment": sale.get_payment_type_display(),
        "balance": get_cash_balance(),
        "client_debt": client.current_debt if client else None,
    }


# --- вспомогательное ---

def _pairs_kb(pairs, prefix):
    rows = [
        [InlineKeyboardButton(text=str(label), callback_data=f"{prefix}:{val}")]
        for val, label in pairs
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_cart(items):
    lines = ["🧾 <b>Корзина:</b>"]
    for i, it in enumerate(items, 1):
        lines.append(
            f"{i}. {it['product_name']} — {it['packs']} "
            f"{pack_label(it['pack_name'], it['packs'])} "
            f"× {it['price_per_unit']} сом/шт"
        )
    return "\n".join(lines)


async def _ask_product(cb_or_msg, state):
    products = await _get_products()
    if not products:
        await cb_or_msg.answer("Нет активных товаров. Сначала добавьте товар в админке.")
        return False
    await state.set_state(SaleFSM.product)
    text = "Выберите товар:"
    kb = _pairs_kb(products, "sale_prod")
    if isinstance(cb_or_msg, CallbackQuery):
        await cb_or_msg.message.edit_text(text, reply_markup=kb)
    else:
        await cb_or_msg.answer(text, reply_markup=kb)
    return True


async def _show_confirm(cb, state):
    data = await state.get_data()
    cart = _render_cart(data["items"])
    pay_label = "Наличные" if data["payment_type"] == "cash" else "Реализация"
    client_line = f"\n👤 Клиент: {data['client_name']}" if data.get("client_name") else ""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="sale_confirm:yes"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="sale_confirm:no"),
        ]]
    )
    await state.set_state(SaleFSM.confirm)
    await cb.message.edit_text(
        f"{cart}\n\n💳 Оплата: <b>{pay_label}</b>{client_line}\n\nОформить продажу?",
        reply_markup=kb,
    )


# --- шаги ---

@router.message(F.text == BTN_SALE)
async def sale_start(message: Message, state: FSMContext):
    await state.clear()
    await state.update_data(items=[])
    await _ask_product(message, state)


@router.callback_query(SaleFSM.product, F.data.startswith("sale_prod:"))
async def sale_product(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split(":")[1])
    info = await _get_product_info(pid)
    await state.update_data(
        cur_product_id=info["id"], cur_product_name=info["name"], cur_pack_name=info["pack_name"]
    )
    await state.set_state(SaleFSM.quantity)
    await cb.message.edit_text(
        f"Товар: <b>{info['name']}</b>\nСколько {info['pack_name']} (фасовок)? Введите число:"
    )
    await cb.answer()


@router.message(SaleFSM.quantity)
async def sale_quantity(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    packs = int(raw) if raw.isdigit() else 0
    if packs <= 0:
        await message.answer("Нужно целое число фасовок (напр. 2). Ещё раз:")
        return
    await state.update_data(cur_packs=packs)
    await state.set_state(SaleFSM.price)
    data = await state.get_data()
    await message.answer(
        f"{data['cur_product_name']}: {packs} "
        f"{pack_label(data['cur_pack_name'], packs)}.\n"
        f"Цена за штуку (сом)?"
    )


@router.message(SaleFSM.price)
async def sale_price(message: Message, state: FSMContext):
    raw = (message.text or "").replace(",", ".").strip()
    try:
        price = Decimal(raw)
    except (InvalidOperation, TypeError):
        price = None
    if price is None or price <= 0:
        await message.answer("Нужна цена — положительное число (напр. 15). Ещё раз:")
        return

    data = await state.get_data()
    items = data.get("items", [])
    items.append({
        "product_id": data["cur_product_id"],
        "product_name": data["cur_product_name"],
        "pack_name": data["cur_pack_name"],
        "packs": data["cur_packs"],
        "price_per_unit": str(price),
    })
    await state.update_data(items=items)
    await state.set_state(SaleFSM.more)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="➕ Добавить ещё", callback_data="sale_more:add"),
            InlineKeyboardButton(text="✅ Дальше", callback_data="sale_more:done"),
        ]]
    )
    await message.answer(
        f"{_render_cart(items)}\n\nДобавить ещё товар или продолжить?", reply_markup=kb
    )


@router.callback_query(SaleFSM.more, F.data == "sale_more:add")
async def sale_more_add(cb: CallbackQuery, state: FSMContext):
    await _ask_product(cb, state)
    await cb.answer()


@router.callback_query(SaleFSM.more, F.data == "sale_more:done")
async def sale_more_done(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SaleFSM.payment)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="💵 Наличные", callback_data="sale_pay:cash"),
            InlineKeyboardButton(text="📦 Реализация", callback_data="sale_pay:debt"),
        ]]
    )
    await cb.message.edit_text("Тип оплаты:", reply_markup=kb)
    await cb.answer()


@router.callback_query(SaleFSM.payment, F.data.startswith("sale_pay:"))
async def sale_payment(cb: CallbackQuery, state: FSMContext):
    pay = cb.data.split(":")[1]  # cash | debt
    await state.update_data(payment_type=pay)
    if pay == "debt":
        clients = await _get_clients()
        if not clients:
            await cb.message.edit_text("Нет клиентов. Для реализации добавьте клиента в админке.")
            await cb.answer()
            return
        await state.set_state(SaleFSM.client)
        await cb.message.edit_text("Выберите клиента:", reply_markup=_pairs_kb(clients, "sale_client"))
    else:
        await state.update_data(client_id=None, client_name=None)
        await _show_confirm(cb, state)
    await cb.answer()


@router.callback_query(SaleFSM.client, F.data.startswith("sale_client:"))
async def sale_client(cb: CallbackQuery, state: FSMContext):
    cid = int(cb.data.split(":")[1])
    clients = dict(await _get_clients())
    await state.update_data(client_id=cid, client_name=clients.get(cid))
    await _show_confirm(cb, state)
    await cb.answer()


@router.callback_query(SaleFSM.confirm, F.data == "sale_confirm:yes")
async def sale_confirm_yes(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    result = await _finalize_sale(data["items"], data["payment_type"], data.get("client_id"))
    await state.clear()

    if result.get("error"):
        await cb.message.edit_text(f"❌ Не удалось провести продажу: {result['error']}")
        await cb.message.answer("Меню:", reply_markup=main_menu())
        await cb.answer()
        return

    msg = (
        f"✅ Продажа #{result['id']} оформлена.\n"
        f"Сумма: <b>{result['total']}</b> сом ({result['payment']})\n"
        f"💰 Касса: <b>{result['balance']}</b> сом"
    )
    if result.get("client_debt") is not None:
        msg += f"\n📦 Долг клиента: <b>{result['client_debt']}</b> сом"
    await cb.message.edit_text(msg)
    await cb.message.answer("Готово 👍", reply_markup=main_menu())
    await cb.answer()


@router.callback_query(SaleFSM.confirm, F.data == "sale_confirm:no")
async def sale_confirm_no(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Продажа отменена.")
    await cb.message.answer("Меню:", reply_markup=main_menu())
    await cb.answer()
