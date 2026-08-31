"""Оркестрация продажи.

process_sale — единственная точка «проведения» продажи. В одной транзакции:
списывает склад по каждой позиции, считает сумму и, по типу оплаты, создаёт
долг или передачу под реализацию. Идемпотентна: повторно не проводит.
Наличные (касса) подключим на шаге finance.
"""
from decimal import Decimal

from django.db import transaction

from apps.debts.services import create_debt
from apps.finance.services import record_sale_income
from apps.warehouse.services import write_off_stock

from .models import Sale, SaleItem


@transaction.atomic
def create_sale(payment_type, items, client=None, comment="") -> Sale:
    """Собрать продажу из позиций и сразу провести её (для бота/скриптов).

    items — список dict: {"product": Product, "packaging": PackagingUnit|None,
    "count": число}. Возвращает проведённую продажу.
    """
    sale = Sale.objects.create(
        payment_type=payment_type, client=client, comment=comment
    )
    for it in items:
        SaleItem.objects.create(
            sale=sale,
            product=it["product"],
            packaging=it.get("packaging"),
            count=it["count"],
        )
    process_sale(sale)
    return sale


@transaction.atomic
def process_sale(sale: Sale) -> Sale:
    if sale.is_processed:
        return sale

    total = Decimal("0")
    for item in sale.items.all():
        write_off_stock(
            item.product, item.base_quantity, comment=f"Продажа #{sale.pk}"
        )
        total += item.line_total

    sale.total = total

    if sale.payment_type == Sale.PaymentType.DEBT:
        create_debt(
            sale.client, total, sale=sale, comment=f"Реализация по продаже #{sale.pk}"
        )
    elif sale.payment_type == Sale.PaymentType.CASH:
        # Наличные сразу падают в кассу.
        record_sale_income(sale)

    sale.is_processed = True
    sale.save(update_fields=["total", "is_processed"])
    return sale
