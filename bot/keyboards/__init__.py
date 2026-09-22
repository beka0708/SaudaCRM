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


def pairs_kb(pairs, prefix: str, columns: int = 2, extra=None) -> InlineKeyboardMarkup:
    """Inline-клавиатура из пар (value, label). callback = f'{prefix}:{value}'.

    По умолчанию в ДВА столбца: списком в один столбец десяток товаров
    занимает весь экран и приходится скроллить. Для длинных подписей
    (например «Клиент — долг 12 345») ставить columns=1.

    `extra` — дополнительные кнопки отдельной строкой внизу.
    """
    buttons = [
        InlineKeyboardButton(text=str(label), callback_data=f"{prefix}:{val}")
        for val, label in pairs
    ]
    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    if extra:
        rows.append(list(extra))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def categories_kb(categories, prefix: str) -> InlineKeyboardMarkup:
    """Inline-клавиатура из категорий TextChoices. callback = f'{prefix}:{value}'."""
    rows = [
        [InlineKeyboardButton(text=c.label, callback_data=f"{prefix}:{c.value}")]
        for c in categories
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
