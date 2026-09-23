"""debts: долги клиентов и частичные оплаты.

Остаток долга не хранится числом — считается как сумма долга минус оплаты.
"""
from decimal import Decimal

from django.db import models
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import ReversibleDocument


class DebtQuerySet(models.QuerySet):
    def active(self):
        """Живые долги — без сторнированных (например, снятых вместе с продажей)."""
        return self.filter(is_reversed=False)


class Debt(ReversibleDocument):
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.PROTECT,
        related_name="debts",
        verbose_name="Клиент",
    )
    sale = models.ForeignKey(
        "sales.Sale",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="debts",
        verbose_name="Продажа-источник",
    )
    amount = models.DecimalField("Сумма долга", max_digits=12, decimal_places=2)
    comment = models.CharField("Комментарий", max_length=255, blank=True)
    # Наследует дату продажи-источника (см. process_sale) — долг по продаже
    # задним числом должен «возникнуть» тогда же, когда была продажа.
    created_at = models.DateTimeField(
        "Возник", default=timezone.now, help_text="По умолчанию — сейчас."
    )

    objects = DebtQuerySet.as_manager()

    class Meta:
        verbose_name = "Долг по реализации"
        verbose_name_plural = "Реализация (долги клиентов)"
        ordering = ["-created_at"]

    def __str__(self):
        mark = " (СТОРНО)" if self.is_reversed else ""
        return f"Долг {self.client}: остаток {self.remaining} из {self.amount}{mark}"

    @property
    def paid(self) -> Decimal:
        # Сторнированные оплаты (ошибочно принятые) в погашение не идут.
        return (
            self.payments.filter(is_reversed=False).aggregate(s=Sum("amount"))["s"]
            or Decimal("0")
        )

    @property
    def remaining(self) -> Decimal:
        return self.amount - self.paid

    @property
    def is_closed(self) -> bool:
        return self.remaining <= 0


class DebtPayment(ReversibleDocument):
    debt = models.ForeignKey(
        Debt, on_delete=models.CASCADE, related_name="payments", verbose_name="Долг"
    )
    amount = models.DecimalField("Сумма оплаты", max_digits=12, decimal_places=2)
    comment = models.CharField("Комментарий", max_length=255, blank=True)
    # НЕ auto_now_add: оплату принимают и «вчерашним числом» (принесли деньги,
    # вбили позже). Дата оплаты задаёт дату прихода в кассу.
    created_at = models.DateTimeField(
        "Дата",
        default=timezone.now,
        help_text="По умолчанию — сейчас. Можно указать прошедшую дату.",
    )

    class Meta:
        verbose_name = "Оплата долга"
        verbose_name_plural = "Оплаты долгов"
        ordering = ["-created_at"]

    def __str__(self):
        mark = " (СТОРНО)" if self.is_reversed else ""
        return f"Оплата {self.amount} по долгу #{self.debt_id}{mark}"

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        # Любая новая оплата долга → приход денег в кассу (единая точка).
        if creating:
            from apps.finance.services import record_debt_payment_income

            record_debt_payment_income(self)