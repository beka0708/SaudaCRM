"""Сценарий «Продажа» (FSM с корзиной).

Шаги: тип оплаты → клиент (для реализации) → товар → количество фасовок →
цена за штуку → (ещё товар?) → подтверждение → провести продажу.

Тип оплаты и клиент идут ПЕРВЫМИ: так корзина сразу собирается «на клиента»,
а не выясняется в самом конце, когда всё уже набрано.
Продают только фасовками; цену вводит продавец (у разных клиентов разная).
Запись — через apps.sales.services.create_sale (FIFO-списание + касса/долг атомарно).

ЦЕНА ВВОДИТСЯ ЗА ШТУКУ, а количество — в фасовках, поэтому на каждом шаге
показываем, сколько штук в фасовке, и сразу считаем сумму позиции. Без этого
легко ввести цену за мешок и промахнуться в разы: 2 мешка по «5 000» при 50
штуках в мешке дают не 10 000, а 500 000, и заметить это было негде.
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
from django.utils import timezone

from apps.analytics.services import money
from apps.catalog.services import pack_label
from bot.keyboards import BTN_SALE, CB_OTHER, main_menu, pairs_kb
from bot.queries import create_client as _create_client
from bot.queries import get_active_clients as _get_clients
from bot.queries import get_product_info as _get_product_info
from bot.queries import get_products as _get_products
from bot.states import SaleFSM

router = Router()


def _line_total(packs, units, price) -> Decimal:
    """Сумма позиции: цена задаётся ЗА ШТУКУ, а количество — в фасовках."""
    return Decimal(int(packs) * int(units)) * Decimal(str(price))


# --- обёртки над ORM/сервисами ---

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
        "client_name": client.name if client else None,
        "date": timezone.localdate(sale.created_at),
    }


# --- вспомогательное ---

def _render_cart(items):
    """Корзина с расшифровкой: фасовки × штук × цена = сумма.

    Расшифровка нужна, чтобы сразу было видно ошибку в цене: цена вводится
    за ШТУКУ, а думают обычно в фасовках — без разбивки «2 мешка по 5 000»
    легко прочитать как 10 000, хотя в мешке 50 штук и выйдет 500 000.
    """
    lines = ["🧾 <b>Корзина</b>"]
    total = Decimal("0")
    for i, it in enumerate(items, 1):
        s = _line_total(it["packs"], it["units"], it["price_per_unit"])
        total += s
        lines.append(
            f"{i}. {it['product_name']}\n"
            f"   {it['packs']} {pack_label(it['pack_name'], it['packs'])}"
            f" × {it['units']} шт × {money(it['price_per_unit'])} сом"
            f" = <b>{money(s)} сом</b>"
        )
    lines.append(f"\n<b>Итого: {money(total)} сом</b>")
    return "\n".join(lines)


async def _ask_product(cb_or_msg, state):
    products = await _get_products()
    if not products:
        await cb_or_msg.answer("Нет активных товаров. Сначала добавьте товар в админке.")
        return False
    await state.set_state(SaleFSM.product)
    text = "Выберите товар:"
    kb = pairs_kb(products, "sale_prod")   # в два столбца — товаров много
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

def _payment_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💵 Наличные", callback_data="sale_pay:cash"),
        InlineKeyboardButton(text="📦 Реализация", callback_data="sale_pay:debt"),
    ]])


@router.message(F.text == BTN_SALE)
async def sale_start(message: Message, state: FSMContext):
    await state.clear()
    await state.update_data(items=[])
    await state.set_state(SaleFSM.payment)
    await message.answer("Как оплачивают?", reply_markup=_payment_kb())


@router.callback_query(SaleFSM.product, F.data.startswith("sale_prod:"))
async def sale_product(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split(":")[1])
    info = await _get_product_info(pid)
    await state.update_data(
        cur_product_id=info["id"], cur_product_name=info["name"],
        cur_pack_name=info["pack_name"], cur_units=info["units"],
    )
    await state.set_state(SaleFSM.quantity)
    # Формулировки подобраны так, чтобы не склонять фасовку по падежам:
    # «1 мешок = 50 шт» — именительный, «Сколько мешков?» — форма мн.ч.
    await cb.message.edit_text(
        f"Товар: <b>{info['name']}</b>\n"
        f"1 {pack_label(info['pack_name'], 1)} = {info['units']} шт\n\n"
        f"Сколько {pack_label(info['pack_name'], 5)}? Введите число:"
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
    units = int(data["cur_units"])
    # Прямо называем, что цена ЗА ШТУКУ, и напоминаем, сколько их в фасовке:
    # именно на этом шаге чаще всего вводят цену за мешок и ошибаются в разы.
    await message.answer(
        f"{data['cur_product_name']}: {packs} "
        f"{pack_label(data['cur_pack_name'], packs)} = {packs * units} шт\n\n"
        f"Цена <b>за 1 ШТУКУ</b> (сом)?\n"
        f"<i>⚠️ не за фасовку: 1 {pack_label(data['cur_pack_name'], 1)} = {units} шт</i>"
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
        "units": int(data["cur_units"]),
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
    # Тип оплаты и клиент выбраны в самом начале — сразу подтверждение.
    await _show_confirm(cb, state)
    await cb.answer()


@router.callback_query(SaleFSM.payment, F.data.startswith("sale_pay:"))
async def sale_payment(cb: CallbackQuery, state: FSMContext):
    pay = cb.data.split(":")[1]  # cash | debt
    await state.update_data(payment_type=pay)

    if pay != "debt":
        await state.update_data(client_id=None, client_name=None)
        await _ask_product(cb, state)
        await cb.answer()
        return

    clients = await _get_clients()
    await state.set_state(SaleFSM.client)
    await cb.message.edit_text(
        "Кому продаём под реализацию?" if clients
        else "Активных клиентов нет — впишите имя:",
        # Три столбца: клиентов много, в один они занимают весь экран.
        reply_markup=pairs_kb(
            clients, "sale_client", columns=3,
            extra=[InlineKeyboardButton(text="✏️ Другой клиент",
                                        callback_data=f"sale_client:{CB_OTHER}")],
        ),
    )
    await cb.answer()


@router.callback_query(SaleFSM.client, F.data == f"sale_client:{CB_OTHER}")
async def sale_client_other(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SaleFSM.new_client)
    await cb.message.edit_text(
        "Напишите имя клиента.\n"
        "<i>Если такого ещё нет — он будет создан автоматически.</i>")
    await cb.answer()


@router.message(SaleFSM.new_client)
async def sale_client_new(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введите имя клиента:")
        return
    cid, cname, created = await _create_client(name)
    await state.update_data(client_id=cid, client_name=cname)
    if created:
        await message.answer(f"👤 Новый клиент: <b>{cname}</b>")
    await _ask_product(message, state)


@router.callback_query(SaleFSM.client, F.data.startswith("sale_client:"))
async def sale_client(cb: CallbackQuery, state: FSMContext):
    cid = int(cb.data.split(":")[1])
    clients = dict(await _get_clients())
    await state.update_data(client_id=cid, client_name=clients.get(cid))
    await _ask_product(cb, state)
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
        f"✅ Продажа #{result['id']} оформлена\n\n"
        f"Сумма: <b>{money(result['total'])} сом</b> ({result['payment']})\n"
        f"💰 Касса: <b>{money(result['balance'])} сом</b>"
    )
    if result.get("client_debt") is not None:
        msg += f"\n📦 Долг клиента: <b>{money(result['client_debt'])} сом</b>"
    await cb.message.edit_text(msg)

    # Для реализации отправляем ВТОРЫМ сообщением текст для самого клиента:
    # его удобно переслать как есть, не вычищая служебные строки бота.
    if result.get("client_name"):
        lines = [f"<b>{result['client_name']}</b>", f"Покупка от {result['date']:%d.%m.%Y}", ""]
        for it in data["items"]:
            s_line = _line_total(it["packs"], it["units"], it["price_per_unit"])
            lines.append(
                f"{it['product_name']} — {it['packs']} "
                f"{pack_label(it['pack_name'], it['packs'])} × "
                f"{money(it['price_per_unit'])} сом = {money(s_line)} сом")
        lines += ["", f"Сумма покупки: {money(result['total'])} сом",
                  f"<b>Общий долг: {money(result['client_debt'])} сом</b>"]
        await cb.message.answer("\n".join(lines))
        await cb.message.answer("↑ можно переслать клиенту", reply_markup=main_menu())
    else:
        await cb.message.answer("Готово 👍", reply_markup=main_menu())
    await cb.answer()


@router.callback_query(SaleFSM.confirm, F.data == "sale_confirm:no")
async def sale_confirm_no(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Продажа отменена.")
    await cb.message.answer("Меню:", reply_markup=main_menu())
    await cb.answer()
