"""finance: журнал движений денег (касса).

Касса нигде не хранится числом — считается как сумма приходов минус расходов
(event-sourcing, как и остаток на складе). Одна модель CashFlow на все деньги:
приходы (продажа, оплата долга, инвестиции) и расходы (закупка, аренда, личные).
"""
from decimal import Decimal

from django.db import models
from django.utils import timezone


class CashFlow(models.Model):
    class Direction(models.TextChoices):
        IN = "in", "Приход"
        OUT = "out", "Расход"

    class Category(models.TextChoices):
        # --- приходы ---
        SALE = "sale", "Продажа (наличные)"
        DEBT_PAYMENT = "debt_payment", "Оплата долга (реализация)"
        INVESTMENT = "investment", "Инвестиции"
        OTHER_IN = "other_in", "Прочий приход"
        # --- расходы ---
        PURCHASE = "purchase", "Закупка товара"
        DELIVERY = "delivery", "Доставка"
        RENT = "rent", "Аренда"
        SALARY = "salary", "Зарплата"
        PERSONAL = "personal", "Личные расходы (Атай)"
        OTHER_OUT = "other_out", "Прочий расход"

    direction = models.CharField("Тип", max_length=8, choices=Direction.choices)
    category = models.CharField("Категория", max_length=20, choices=Category.choices)
    # Своя статья расхода из бота: «Сушняк», «Стоянка», «Шоппинг» и т.п.
    # Категория выше остаётся укрупнённой (для кассы и прибыли), а здесь
    # хранится то, что реально выбрал человек — по ней можно фильтровать
    # и группировать, не плодя два десятка значений в Category.
    subcategory = models.CharField("Статья", max_length=64, blank=True)
    amount = models.DecimalField("Сумма", max_digits=14, decimal_places=2)
    date = models.DateField("Дата", default=timezone.localdate)
    comment = models.CharField("Комментарий", max_length=255, blank=True)

    # Ссылки на источник (для авто-проводок из продаж/оплат) — необязательные.
    sale = models.ForeignKey(
        "sales.Sale",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_flows",
        verbose_name="Продажа-источник",
    )
    debt_payment = models.ForeignKey(
        "debts.DebtPayment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_flows",
        verbose_name="Оплата долга-источник",
    )

    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Движение денег"
        verbose_name_plural = "Касса / движения денег"
        ordering = ["-date", "-created_at"]
        indexes = [models.Index(fields=["direction", "date"])]

    def __str__(self):
        sign = "+" if self.direction == self.Direction.IN else "−"
        return f"{sign}{self.amount} ({self.get_category_display()})"

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.direction == self.Direction.IN else -self.amount
