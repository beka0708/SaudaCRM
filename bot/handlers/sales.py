"""Сценарий «Продажа» (FSM с корзиной).

Шаги: товар → фасовка/поштучно → количество → (ещё товар?) → тип оплаты →
клиент (для реализации) → подтверждение → провести продажу.
Вся запись — через apps.sales.services.create_sale (склад + касса/долг атомарно).
ORM-вызовы обёрнуты в sync_to_async.
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

from bot.keyboards import BTN_SALE, main_menu
from bot.states import SaleFSM

router = Router()


# --- обёртки над ORM/сервисами ---

@sync_to_async
def _get_products():
    from apps.catalog.models import Product

    return list(Product.objects.filter(is_active=True).values_list("id", "name"))


@sync_to_async
def _get_product_info(pid):
    from apps.catalog.models import Product

    p = Product.objects.get(pk=pid)
    return {"id": p.id, "name": p.name, "base_unit": p.base_unit}


@sync_to_async
def _get_packagings(pid):
    from apps.catalog.models import PackagingUnit
    from apps.catalog.services import fmt_qty

    out = []
    for pack in PackagingUnit.objects.filter(product_id=pid).select_related("product"):
        label = f"{pack.name} = {fmt_qty(pack.quantity_in_base)} {pack.product.base_unit}"
        out.append((pack.id, label, pack.name))
    return out


@sync_to_async
def _get_clients():
    from apps.clients.models import Client

    return list(Client.objects.values_list("id", "name"))


@sync_to_async
def _finalize_sale(items, payment_type, client_id):
    from apps.catalog.models import PackagingUnit, Product
    from apps.clients.models import Client
    from apps.finance.services import get_cash_balance
    from apps.sales.services import create_sale

    resolved = []
    for it in items:
        product = Product.objects.get(pk=it["product_id"])
        packaging = (
            PackagingUnit.objects.get(pk=it["packaging_id"])
            if it.get("packaging_id")
            else None
        )
        resolved.append({"product": product, "packaging": packaging, "count": it["count"]})

    client = Client.objects.get(pk=client_id) if client_id else None
    sale = create_sale(payment_type, resolved, client=client)
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
        unit = it["packaging_name"] or it["base_unit"]
        lines.append(f"{i}. {it['product_name']} — {it['count']} {unit}")
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
    packs = await _get_packagings(pid)
    await state.update_data(
        cur_product_id=info["id"],
        cur_product_name=info["name"],
        cur_base_unit=info["base_unit"],
        cur_packs={pk: name for pk, _label, name in packs},
    )
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"sale_pack:{pk}")]
        for pk, label, _name in packs
    ]
    rows.append(
        [InlineKeyboardButton(text=f"поштучно ({info['base_unit']})", callback_data="sale_pack:base")]
    )
    await state.set_state(SaleFSM.packaging)
    await cb.message.edit_text(
        f"Товар: <b>{info['name']}</b>\nВыберите фасовку или поштучно:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cb.answer()


@router.callback_query(SaleFSM.packaging, F.data.startswith("sale_pack:"))
async def sale_packaging(cb: CallbackQuery, state: FSMContext):
    val = cb.data.split(":")[1]
    data = await state.get_data()
    if val == "base":
        pack_id, pack_name, unit_label = None, None, data["cur_base_unit"]
    else:
        pack_id = int(val)
        pack_name = data["cur_packs"].get(pack_id)
        unit_label = pack_name
    await state.update_data(cur_packaging_id=pack_id, cur_packaging_name=pack_name)
    await state.set_state(SaleFSM.quantity)
    await cb.message.edit_text(f"Сколько ({unit_label})? Введите число:")
    await cb.answer()


@router.message(SaleFSM.quantity)
async def sale_quantity(message: Message, state: FSMContext):
    raw = (message.text or "").replace(",", ".").strip()
    try:
        count = Decimal(raw)
    except (InvalidOperation, TypeError):
        count = None
    if count is None or count <= 0:
        await message.answer("Нужно положительное число. Ещё раз:")
        return

    data = await state.get_data()
    items = data.get("items", [])
    items.append(
        {
            "product_id": data["cur_product_id"],
            "product_name": data["cur_product_name"],
            "base_unit": data["cur_base_unit"],
            "packaging_id": data.get("cur_packaging_id"),
            "packaging_name": data.get("cur_packaging_name"),
            "count": str(count),
        }
    )
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
            await cb.message.edit_text(
                "Нет клиентов. Для реализации добавьте клиента в админке."
            )
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
