"""Бизнес-логика catalog: форматирование остатка/количеств.

Этот слой вызывают И админка, И Telegram-бот.
"""
from decimal import Decimal


def fmt_qty(value) -> str:
    """Человекочитаемое число без лишних нулей: 91.000 -> '91', 2.500 -> '2.5'."""
    s = f"{Decimal(str(value)):f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Русская форма множественного числа: 1 коробка, 2 коробки, 5 коробок."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


# Фасовки, которые реально заводит заказчик. Для незнакомого слова склонять
# не пытаемся — оставляем как ввели (лучше «5 ящик», чем неверная форма).
_PACK_FORMS = {
    "коробка": ("коробка", "коробки", "коробок"),
    "мешок": ("мешок", "мешка", "мешков"),
    "блок": ("блок", "блока", "блоков"),
    "пачка": ("пачка", "пачки", "пачек"),
    "ящик": ("ящик", "ящика", "ящиков"),
    "упаковка": ("упаковка", "упаковки", "упаковок"),
    "бутылка": ("бутылка", "бутылки", "бутылок"),
    "банка": ("банка", "банки", "банок"),
    "рулон": ("рулон", "рулона", "рулонов"),
    "штука": ("штука", "штуки", "штук"),
}


def pack_label(pack_name: str, packs: int) -> str:
    """«коробка» + 5 → «коробок». Незнакомую фасовку возвращаем как есть."""
    forms = _PACK_FORMS.get((pack_name or "").strip().lower())
    return plural_ru(packs, *forms) if forms else pack_name


def stock_breakdown(product, packs=None) -> str:
    """Остаток в фасовках: «5 коробок» (+ «(480 шт)», если фасовка не 1-штучная)."""
    if packs is None:
        packs = product.stock
    packs = int(packs)
    label = f"{packs} {pack_label(product.pack_name, packs)}"
    if product.units_per_pack and product.units_per_pack != 1:
        label += f" ({packs * product.units_per_pack} {product.base_unit})"
    return label
