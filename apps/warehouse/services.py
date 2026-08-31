"""Бизнес-логика склада: расчёт остатка и запись движений.

Эти функции — единая точка изменения склада. Их вызывают админка, бот и
apps.sales (при продаже). Количество везде в БАЗОВЫХ единицах товара.
"""
from decimal import Decimal

from django.db.models import Sum

from .models import StockMovement


def _dec(value) -> Decimal:
    return Decimal(str(value))


def get_stock(product) -> Decimal:
    """Текущий остаток товара = сумма всех его движений."""
    total = product.movements.aggregate(s=Sum("quantity"))["s"]
    return total or Decimal("0")


def record_movement(product, quantity, movement_type, comment="") -> StockMovement:
    """Записать движение. quantity — СО ЗНАКОМ, в базовых единицах."""
    return StockMovement.objects.create(
        product=product,
        quantity=_dec(quantity),
        movement_type=movement_type,
        comment=comment,
    )


def receive_stock(product, base_quantity, comment="") -> StockMovement:
    """Приход: увеличить остаток на base_quantity (положительное движение)."""
    return record_movement(
        product, abs(_dec(base_quantity)), StockMovement.Type.RECEIPT, comment
    )


def write_off_stock(product, base_quantity, comment="") -> StockMovement:
    """Списание (продажа): уменьшить остаток (отрицательное движение)."""
    return record_movement(
        product, -abs(_dec(base_quantity)), StockMovement.Type.SALE, comment
    )


def adjust_stock(product, delta, comment="") -> StockMovement:
    """Корректировка остатка: delta со знаком (+ добавить, − убавить)."""
    return record_movement(
        product, _dec(delta), StockMovement.Type.ADJUSTMENT, comment
    )
