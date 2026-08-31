"""Бизнес-логика catalog: пересчёт фасовок в базовые единицы.

Этот слой вызывают И админка, И Telegram-бот.
"""
from decimal import Decimal


def to_base_units(product, count, packaging=None) -> Decimal:
    """Перевести count единиц выбранной фасовки в базовые единицы товара.

    packaging=None → count уже задан в базовых единицах.
    Напр.: to_base_units(мыло, 1, коробка(96)) -> 96.
    """
    count = Decimal(str(count))
    if packaging is None:
        return count
    return count * packaging.quantity_in_base


def fmt_qty(value) -> str:
    """Человекочитаемое число без лишних нулей: 91.000 -> '91', 2.500 -> '2.5'."""
    s = f"{Decimal(str(value)):f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def stock_breakdown(product, stock=None) -> str:
    """Разбить остаток по САМОЙ КРУПНОЙ фасовке товара для наглядности.

    Примеры (коробка = 96 шт):
        101 -> '1 коробка + 5 шт'
         91 -> '91 шт'   (до коробки не хватает 5 шт)
        192 -> '2 коробки'
    Без фасовок — просто '<кол-во> <база>'. Внутри всё равно храним базовые ед.
    """
    if stock is None:
        stock = product.stock
    stock = Decimal(str(stock))
    base = product.base_unit

    largest = product.packagings.order_by("-quantity_in_base").first()
    if largest is None or largest.quantity_in_base <= 1:
        return f"{fmt_qty(stock)} {base}"

    full = int(stock // largest.quantity_in_base)
    remainder = stock - full * largest.quantity_in_base

    parts = []
    if full:
        # «2 × коробка» — нейтрально к русскому склонению (не «2 коробка»).
        parts.append(f"{full} × {largest.name}")
    if remainder or not full:
        parts.append(f"{fmt_qty(remainder)} {base}")
    return " + ".join(parts)
