"""debts: долги клиентов и частичные оплаты.

Остаток долга не хранится числом — считается как сумма долга минус оплаты.
"""
from decimal import Decimal

from django.db import models
from django.db.models import Sum


class Debt(models.Model):
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
    created_at = models.DateTimeField("Возник", auto_now_add=True)

    class Meta:
        verbose_name = "Долг по реализации"
        verbose_name_plural = "Реализация (долги клиентов)"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Долг {self.client}: остаток {self.remaining} из {self.amount}"

    @property
    def paid(self) -> Decimal:
        return self.payments.aggregate(s=Sum("amount"))["s"] or Decimal("0")

    @property
    def remaining(self) -> Decimal:
        return self.amount - self.paid

    @property
    def is_closed(self) -> bool:
        return self.remaining <= 0


class DebtPayment(models.Model):
    debt = models.ForeignKey(
        Debt, on_delete=models.CASCADE, related_name="payments", verbose_name="Долг"
    )
    amount = models.DecimalField("Сумма оплаты", max_digits=12, decimal_places=2)
    comment = models.CharField("Комментарий", max_length=255, blank=True)
    created_at = models.DateTimeField("Дата", auto_now_add=True)

    class Meta:
        verbose_name = "Оплата долга"
        verbose_name_plural = "Оплаты долгов"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Оплата {self.amount} по долгу #{self.debt_id}"

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        # Любая новая оплата долга → приход денег в кассу (единая точка).
        if creating:
            from apps.finance.services import record_debt_payment_income

            record_debt_payment_income(self)