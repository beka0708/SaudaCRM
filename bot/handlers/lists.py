"""Кнопка «Список»: быстро посмотреть остатки и долги прямо в боте.

До этого актуальные цифры можно было увидеть только в админке — на
телефоне это неудобно, а нужны они постоянно: «сколько осталось мыла»,
«сколько должен Улан». Поэтому две сводки одним нажатием.

Выводим КОРОТКО: товар и число, клиент и сумма. Подробности — в админке.
"""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async

from bot.keyboards import BTN_LIST, main_menu

router = Router()

# Telegram рвёт сообщения длиннее 4096 символов — режем с запасом.
_LIMIT = 3500


@sync_to_async
def _stock():
    from apps.analytics.services import money, stock_report

    rows, total = stock_report()
    if not rows:
        return "📦 <b>Склад пуст</b>"
    # pack_label из stock_report уже в нужной форме («коробок», «мешка»).
    lines = ["📦 <b>Остатки на складе</b>\n"]
    for r in rows:
        lines.append(f"{r['name']} — <b>{r['packs']}</b> {r['pack_label']}")
    lines.append(f"\nВсего по себестоимости: <b>{money(total)} сом</b>")
    return "\n".join(lines)


@sync_to_async
def _debtors():
    from apps.analytics.services import all_debtors, money

    rows, total = all_debtors()
    if not rows:
        return "👥 <b>Должников нет</b>"
    lines = [f"👥 <b>Должники — {len(rows)}</b>\n"]
    for r in rows:
        lines.append(f"{r['name']} — <b>{money(r['debt'])}</b>")
    lines.append(f"\nИтого должны: <b>{money(total)} сом</b>")
    return "\n".join(lines)


def _chunks(text):
    """Разбить длинный список по строкам, не разрывая строку посередине."""
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > _LIMIT:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts


@router.message(F.text == BTN_LIST)
async def list_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Что показать?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📦 Товары", callback_data="list:stock"),
            InlineKeyboardButton(text="👥 Клиенты", callback_data="list:debtors"),
        ]]),
    )


@router.callback_query(F.data.startswith("list:"))
async def list_show(cb: CallbackQuery):
    kind = cb.data.split(":")[1]
    text = await (_stock() if kind == "stock" else _debtors())
    parts = _chunks(text)
    await cb.message.edit_text(parts[0])
    for extra in parts[1:]:
        await cb.message.answer(extra)
    await cb.message.answer("Меню:", reply_markup=main_menu())
    await cb.answer()
