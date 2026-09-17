"""Клавиатуры бота."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Кнопки главного меню (по мере добавления сценариев расширяем).
BTN_SALE = "🧾 Продажа"
BTN_RECEIPT = "📥 Приход"
BTN_DEBT = "💰 Оплата долга"
BTN_EXPENSE = "➖ Расход"
BTN_UNDO = "↩️ Отменить"


def main_menu() -> ReplyKeyboardMarkup:
    # Четыре ежедневных сценария сверху, отмена — отдельной строкой ниже:
    # ею пользуются редко, и случайно нажать её не должно быть легко.
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SALE), KeyboardButton(text=BTN_RECEIPT)],
            [KeyboardButton(text=BTN_DEBT), KeyboardButton(text=BTN_EXPENSE)],
            [KeyboardButton(text=BTN_UNDO)],
        ],
        resize_keyboard=True,
    )


def pairs_kb(pairs, prefix: str) -> InlineKeyboardMarkup:
    """Inline-клавиатура из пар (value, label). callback = f'{prefix}:{value}'."""
    rows = [
        [InlineKeyboardButton(text=str(label), callback_data=f"{prefix}:{val}")]
        for val, label in pairs
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def categories_kb(categories, prefix: str) -> InlineKeyboardMarkup:
    """Inline-клавиатура из категорий TextChoices. callback = f'{prefix}:{value}'."""
    rows = [
        [InlineKeyboardButton(text=c.label, callback_data=f"{prefix}:{c.value}")]
        for c in categories
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
