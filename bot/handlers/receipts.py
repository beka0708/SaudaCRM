"""Сценарий «Приход партии» (FSM) — с возможностью добавить новый товар.

Шаги: товар (или «➕ новый» → имя/фасовка/штук) → кол-во фасовок →
себестоимость за штуку → подтверждение → оприходовать партию.
Приход автоматически списывает «Закупку» из кассы (Batch.save).
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

from apps.analytics.services import money
from apps.catalog.services import pack_label
from bot.keyboards import BTN_RECEIPT, main_menu, pairs_kb
from bot.queries import get_product_info as _get_product_info
from bot.queries import get_products as _get_products
from bot.states import ReceiptFSM

router = Router()


@sync_to_async
def _finalize_receipt(data):
    from django.db import IntegrityError

    from apps.catalog.models import Product
    from apps.finance.services import get_cash_balance
    from apps.warehouse.services import get_stock, receive_batch

    if data.get("new"):
        try:
            product = Product.objects.create(
                name=data["name"], pack_name=data["pack_name"], units_per_pack=int(data["units"])
            )
        except IntegrityError:
            return {"error": f"Товар «{data['name']}» уже существует."}
    else:
        product = Product.objects.get(pk=data["product_id"])

    packs = int(data["packs"])
    cost = Decimal(str(data["cost"]))
    receive_batch(product, packs, cost)
    return {
        "name": product.name,
        "pack_name": product.pack_name,
        "packs": packs,
        "stock": get_stock(product),
        "balance": get_cash_balance(),
        "purchase": Decimal(packs * product.units_per_pack) * cost,
    }


def _products_kb(products):
    # В два столбца — товаров много, одним списком занимают весь экран.
    # Кнопка «Новый товар» отдельной строкой внизу, чтобы не нажать случайно.
    return pairs_kb(
        products, "rcpt_prod",
        extra=[InlineKeyboardButton(text="➕ Новый товар", callback_data="rcpt_prod:new")],
    )


async def _ask_packs(message_or_cb, state, product_name, pack_name, units):
    await state.set_state(ReceiptFSM.packs)
    text = (
        f"Приход: <b>{product_name}</b>\n"
        f"1 {pack_label(pack_name, 1)} = {units} шт\n\n"
        f"Сколько {pack_label(pack_name, 5)} пришло?"
    )
    if isinstance(message_or_cb, CallbackQuery):
        await message_or_cb.message.edit_text(text)
    else:
        await message_or_cb.answer(text)


# --- шаги ---

@router.message(F.text == BTN_RECEIPT)
async def receipt_start(message: Message, state: FSMContext):
    await state.clear()
    products = await _get_products()
    await state.set_state(ReceiptFSM.product)
    await message.answer(
        "Что приходуем? Выберите товар или добавьте новый:",
        reply_markup=_products_kb(products),
    )


@router.callback_query(ReceiptFSM.product, F.data == "rcpt_prod:new")
async def receipt_new(cb: CallbackQuery, state: FSMContext):
    await state.update_data(new=True)
    await state.set_state(ReceiptFSM.new_name)
    await cb.message.edit_text("Название нового товара:")
    await cb.answer()


@router.callback_query(ReceiptFSM.product, F.data.startswith("rcpt_prod:"))
async def receipt_product(cb: CallbackQuery, state: FSMContext):
    info = await _get_product_info(int(cb.data.split(":")[1]))
    await state.update_data(
        new=False, product_id=info["id"], product_name=info["name"],
        pack_name=info["pack_name"], units=info["units"],
    )
    await _ask_packs(cb, state, info["name"], info["pack_name"], info["units"])
    await cb.answer()


@router.message(ReceiptFSM.new_name)
async def receipt_new_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введите название:")
        return
    await state.update_data(name=name)
    await state.set_state(ReceiptFSM.new_pack)
    await message.answer("Как называется фасовка? (коробка / блок / мешок…)")


@router.message(ReceiptFSM.new_pack)
async def receipt_new_pack(message: Message, state: FSMContext):
    pack = (message.text or "").strip()
    if not pack:
        await message.answer("Введите название фасовки:")
        return
    await state.update_data(pack_name=pack)
    await state.set_state(ReceiptFSM.new_units)
    await message.answer(f"Сколько штук в одной «{pack}»? (напр. 96)")


@router.message(ReceiptFSM.new_units)
async def receipt_new_units(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    units = int(raw) if raw.isdigit() else 0
    if units <= 0:
        await message.answer("Нужно целое число (напр. 96). Ещё раз:")
        return
    await state.update_data(units=units)
    data = await state.get_data()
    await _ask_packs(message, state, data["name"], data["pack_name"], data["units"])


@router.message(ReceiptFSM.packs)
async def receipt_packs(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    packs = int(raw) if raw.isdigit() else 0
    if packs <= 0:
        await message.answer("Нужно целое число фасовок (напр. 5). Ещё раз:")
        return
    await state.update_data(packs=packs)
    await state.set_state(ReceiptFSM.cost)
    data = await state.get_data()
    units = int(data["units"])
    pack = data["pack_name"]
    # Как и в продаже: себестоимость вводится ЗА ШТУКУ, поэтому явно
    # напоминаем, сколько их в фасовке, и показываем итог.
    await message.answer(
        f"{packs} {pack_label(pack, packs)} = {packs * units} шт\n\n"
        f"Себестоимость <b>за 1 ШТУКУ</b> (сом)?\n"
        f"<i>⚠️ не за фасовку: 1 {pack_label(pack, 1)} = {units} шт</i>"
    )


@router.message(ReceiptFSM.cost)
async def receipt_cost(message: Message, state: FSMContext):
    raw = (message.text or "").replace(",", ".").strip()
    try:
        cost = Decimal(raw)
    except (InvalidOperation, TypeError):
        cost = None
    if cost is None or cost <= 0:
        await message.answer("Нужна себестоимость — положительное число. Ещё раз:")
        return
    await state.update_data(cost=str(cost))

    data = await state.get_data()
    purchase = data["packs"] * int(data["units"]) * cost
    await state.set_state(ReceiptFSM.confirm)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Оприходовать", callback_data="rcpt_ok:yes"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="rcpt_ok:no"),
    ]])
    name = data.get("name") or data.get("product_name")
    units = int(data["units"])
    await message.answer(
        f"Приход: <b>{name}</b>\n\n"
        f"{data['packs']} {pack_label(data['pack_name'], data['packs'])}"
        f" × {units} шт × {money(cost)} сом"
        f" = <b>{money(purchase)} сом</b>\n\n"
        f"💸 Спишется из кассы: <b>{money(purchase)} сом</b>\n\nПодтвердить?",
        reply_markup=kb,
    )


@router.callback_query(ReceiptFSM.confirm, F.data == "rcpt_ok:yes")
async def receipt_confirm(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    result = await _finalize_receipt(data)
    await state.clear()
    if result.get("error"):
        await cb.message.edit_text(f"❌ {result['error']}")
        await cb.message.answer("Меню:", reply_markup=main_menu())
        await cb.answer()
        return
    await cb.message.edit_text(
        f"✅ Приход оформлен: <b>{result['name']}</b>\n\n"
        f"📦 Пришло: +{result['packs']} "
        f"{pack_label(result['pack_name'], result['packs'])}\n"
        f"📦 Остаток: <b>{result['stock']} "
        f"{pack_label(result['pack_name'], result['stock'])}</b>\n"
        f"💸 Закупка: {money(result['purchase'])} сом\n"
        f"💰 Касса: <b>{money(result['balance'])} сом</b>"
    )
    await cb.message.answer("Готово 👍", reply_markup=main_menu())
    await cb.answer()


@router.callback_query(ReceiptFSM.confirm, F.data == "rcpt_ok:no")
async def receipt_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Приход отменён.")
    await cb.message.answer("Меню:", reply_markup=main_menu())
    await cb.answer()
