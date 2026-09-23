"""Бизнес-логика долгов: создание долга, погашение, расчёт остатка.

Вызывают И админка, И бот, И sales (при продаже в долг).
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Debt, DebtPayment


def _dec(value) -> Decimal:
    return Decimal(str(value))


def create_debt(client, amount, sale=None, comment="", created_at=None) -> Debt:
    """Создать долг клиенту (например, при продаже в долг).

    `created_at` — дата возникновения долга (для продажи задним числом равна
    дате продажи). По умолчанию — сейчас.
    """
    fields = {"client": client, "amount": _dec(amount), "sale": sale, "comment": comment}
    if created_at is not None:
        fields["created_at"] = created_at
    return Debt.objects.create(**fields)


def client_total_debt(client) -> Decimal:
    """Текущий общий долг клиента = сумма остатков по всем его ЖИВЫХ долгам."""
    total = Decimal("0")
    for debt in client.debts.filter(is_reversed=False):
        total += debt.remaining
    return total


@transaction.atomic
def add_payment(client, amount, comment="", created_at=None) -> list[DebtPayment]:
    """Погашение долга клиента.

    Оплату распределяем по открытым долгам от старых к новым (FIFO).
    Возвращаем список созданных оплат. Атомарно: сбой в середине распределения
    не оставит часть оплат с проводками в кассе.

    Переплату НЕ моделируем (решение заказчика): если клиент дал больше долга,
    вносится сумма по факту долга, остаток игнорируется.

    `created_at` — дата оплаты (задаёт и дату прихода в кассу). По умолчанию — сейчас.
    """
    remaining = _dec(amount)
    payments = []
    for debt in client.debts.filter(is_reversed=False).order_by("created_at"):
        if remaining <= 0:
            break
        due = debt.remaining
        if due <= 0:
            continue
        pay = min(due, remaining)
        # Проводку в кассу делает DebtPayment.save() — здесь только создаём оплату.
        fields = {"debt": debt, "amount": pay, "comment": comment}
        if created_at is not None:
            fields["created_at"] = created_at
        payment = DebtPayment.objects.create(**fields)
        payments.append(payment)
        remaining -= pay
    return payments


@transaction.atomic
def reverse_debt_payment(payment: DebtPayment, user=None, reason="") -> DebtPayment:
    """Сторнировать ошибочно принятую оплату долга.

    Деньги уходят обратно из кассы обратной проводкой (датой самой оплаты,
    чтобы отчёт за период сошёлся), а долг снова становится непогашенным —
    `Debt.paid` сторнированные оплаты не считает. Идемпотентна.
    """
    # Сверяемся с БД: повторное сторно вернуло бы деньги из кассы дважды.
    payment.refresh_from_db()
    if payment.is_reversed:
        return payment

    from apps.finance.models import CashFlow
    from apps.finance.services import record_cash_flow

    record_cash_flow(
        CashFlow.Direction.OUT,
        CashFlow.Category.DEBT_PAYMENT,
        payment.amount,
        date=timezone.localdate(payment.created_at),
        comment=f"Сторно оплаты долга #{payment.debt_id}",
        debt_payment=payment,
    )
    payment.mark_reversed(user, reason)
    payment.save(
        update_fields=["is_reversed", "reversed_at", "reversed_by", "reversal_reason"]
    )
    return payment