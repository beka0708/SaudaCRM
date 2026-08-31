"""Бизнес-логика долгов: создание долга, погашение, расчёт остатка.

Вызывают И админка, И бот, И sales (при продаже в долг).
"""
from decimal import Decimal

from .models import Debt, DebtPayment


def _dec(value) -> Decimal:
    return Decimal(str(value))


def create_debt(client, amount, sale=None, comment="") -> Debt:
    """Создать долг клиенту (например, при продаже в долг)."""
    return Debt.objects.create(
        client=client, amount=_dec(amount), sale=sale, comment=comment
    )


def client_total_debt(client) -> Decimal:
    """Текущий общий долг клиента = сумма остатков по всем его долгам."""
    total = Decimal("0")
    for debt in client.debts.all():
        total += debt.remaining
    return total


def add_payment(client, amount, comment="") -> list[DebtPayment]:
    """Погашение долга клиента.

    Оплату распределяем по открытым долгам от старых к новым (FIFO).
    Возвращаем список созданных оплат. Переплата (если долгов меньше суммы)
    пока игнорируется — см. backlog.
    """
    remaining = _dec(amount)
    payments = []
    for debt in client.debts.order_by("created_at"):
        if remaining <= 0:
            break
        due = debt.remaining
        if due <= 0:
            continue
        pay = min(due, remaining)
        # Проводку в кассу делает DebtPayment.save() — здесь только создаём оплату.
        payment = DebtPayment.objects.create(debt=debt, amount=pay, comment=comment)
        payments.append(payment)
        remaining -= pay
    return payments