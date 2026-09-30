"""Оркестрация продажи (партионный учёт, FIFO).

process_sale — единственная точка «проведения»: в одной транзакции списывает
склад по FIFO (считая себестоимость каждой позиции), суммирует выручку и по
типу оплаты создаёт долг или приход в кассу. Идемпотентна.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.debts.services import create_debt
from apps.finance.services import record_sale_income
from apps.warehouse.services import consume_fifo, restore_sale_stock

from .models import Sale, SaleItem


@transaction.atomic
def create_sale(payment_type, items, client=None, comment="", created_at=None) -> Sale:
    """Собрать продажу и провести. items — список {"product", "packs", "price_per_unit"}.

    `created_at` — дата продажи (по умолчанию сейчас). Задаёт и дату проводки
    в кассе, и дату долга: продажу можно провести задним числом.
    """
    fields = {"payment_type": payment_type, "client": client, "comment": comment}
    if created_at is not None:
        fields["created_at"] = created_at
    sale = Sale.objects.create(**fields)
    for it in items:
        SaleItem.objects.create(
            sale=sale,
            product=it["product"],
            packs=int(it["packs"]),
            price_per_unit=Decimal(str(it["price_per_unit"])),
        )
    process_sale(sale)
    return sale


@transaction.atomic
def process_sale(sale: Sale) -> Sale:
    if sale.is_processed:
        return sale

    total = Decimal("0")
    for item in sale.items.all():
        # consume_fifo кидает ValidationError при нехватке — вся транзакция откатится.
        item.cogs = consume_fifo(item)
        # Снимок выручки: считаем ОДИН раз, на момент продажи.
        item.revenue = item.line_total
        item.save(update_fields=["cogs", "revenue"])
        total += item.revenue

    sale.total = total

    if sale.payment_type == Sale.PaymentType.DEBT:
        create_debt(
            sale.client,
            total,
            sale=sale,
            comment=f"Реализация по продаже #{sale.pk}",
            created_at=sale.created_at,
        )
    elif sale.payment_type == Sale.PaymentType.CASH:
        record_sale_income(sale)

    sale.is_processed = True
    sale.save(update_fields=["total", "is_processed"])
    return sale


@transaction.atomic
def reverse_sale(sale: Sale, user=None, reason="") -> Sale:
    """Сторнировать проведённую продажу — отменить её последствия.

    Компенсации (всё в одной транзакции):
      1) фасовки возвращаются в те же партии, из которых списались (FIFO-история
         сохраняется — `BatchConsumption` не удаляем);
      2) наличная продажа — обратная проводка (расход) на сумму продажи;
      3) реализация — созданный долг помечается сторнированным.

    Обратная проводка датируется ДАТОЙ ПРОДАЖИ, а не сегодняшним днём: так
    отчёт за тот период сходится в ноль, а когда сторно сделали реально —
    видно в `reversed_at`. Идемпотентна: повторный вызов ничего не делает.
    """
    # Сверяемся с БД: переданный объект мог устареть, а повторное сторно
    # вернуло бы товар в партии дважды.
    sale.refresh_from_db()
    if sale.is_reversed:
        return sale
    if not sale.is_processed:
        raise ValidationError(f"Продажа #{sale.pk} не проведена — сторнировать нечего.")

    # По реализации могли уже принять деньги — тогда сторно продажи оставило бы
    # «висящую» оплату. Сначала сторнируется оплата (debts.reverse_debt_payment).
    debts = list(sale.debts.filter(is_reversed=False))
    for debt in debts:
        if debt.paid > 0:
            raise ValidationError(
                f"По продаже #{sale.pk} уже принято {debt.paid} сом оплаты долга. "
                f"Сначала сторнируйте оплату, потом продажу."
            )

    restore_sale_stock(sale)

    if sale.payment_type == Sale.PaymentType.CASH:
        from apps.finance.models import CashFlow
        from apps.finance.services import record_cash_flow

        record_cash_flow(
            CashFlow.Direction.OUT,
            CashFlow.Category.SALE,
            sale.total,
            date=timezone.localdate(sale.created_at),
            comment=f"Сторно продажи #{sale.pk}",
            sale=sale,
        )
    else:
        for debt in debts:
            debt.mark_reversed(user, reason or f"Сторно продажи #{sale.pk}")
            debt.save(
                update_fields=[
                    "is_reversed", "reversed_at", "reversed_by", "reversal_reason",
                ]
            )

    sale.mark_reversed(user, reason)
    sale.save(
        update_fields=["is_reversed", "reversed_at", "reversed_by", "reversal_reason"]
    )
    return sale
