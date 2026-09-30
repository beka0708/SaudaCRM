"""clients: карточка клиента. Долг и товар на реализации — производные."""
from decimal import Decimal

from django.db import models


class Client(models.Model):
    name = models.CharField("ФИО / магазин", max_length=255)
    phone = models.CharField("Телефон", max_length=32, blank=True)
    address = models.CharField("Адрес", max_length=255, blank=True)
    comment = models.TextField("Комментарий", blank=True)
    is_active = models.BooleanField(
        "Активный",
        default=True,
        help_text="Неактивные не показываются в боте при продаже и оплате долга. "
        "Историю и долги не трогает — просто убирает из списков выбора.",
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Клиент"
        verbose_name_plural = "Клиенты"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def current_debt(self) -> Decimal:
        """Текущий общий долг клиента по реализации (остаток по всем долгам)."""
        from apps.debts.services import client_total_debt

        return client_total_debt(self)
