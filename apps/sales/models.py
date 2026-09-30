"""sales: продажа (Sale) и её позиции (SaleItem).

Продают ТОЛЬКО фасовками (целое кол-во). Цена вводится при продаже (за штуку).
Себестоимость позиции (cogs) считается по FIFO при проведении. Продажа —
«документ»: после проведения не редактируется. Оркестрация — process_sale().
"""
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.core.models import ReversibleDocument


class SaleQuerySet(models.QuerySet):
    def active(self):
        """Живые продажи — без сторнированных.

        Для выручки/прибыли/ТОПов брать ИМЕННО это: сторнированная продажа не
        должна попадать в аналитику и отчёты. В админке, наоборот, показываем
        всё — сторно видно в истории.
        """
        return self.filter(is_reversed=False)


class Sale(ReversibleDocument):
    class PaymentType(models.TextChoices):
        CASH = "cash", "Наличные"
        # «Реализация» = денежный долг: клиент взял товар, должен сумму.
        DEBT = "debt", "Реализация"

    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sales",
        verbose_name="Клиент",
        help_text="Для наличной продажи можно не указывать.",
    )
    payment_type = models.CharField(
        "Тип оплаты", max_length=16, choices=PaymentType.choices, default=PaymentType.CASH
    )
    total = models.DecimalField(
        "Сумма продажи", max_digits=14, decimal_places=2, default=0, editable=False
    )
    comment = models.CharField("Комментарий", max_length=255, blank=True)
    is_processed = models.BooleanField("Проведена", default=False, editable=False)
    # НЕ auto_now_add: продажу нужно уметь провести задним числом (забыли вбить
    # вчера, импорт истории из Excel). Дата документа задаёт и дату проводки в кассе.
    created_at = models.DateTimeField(
        "Дата продажи",
        default=timezone.now,
        help_text="По умолчанию — сейчас. Можно указать прошедшую дату.",
    )

    objects = SaleQuerySet.as_manager()

    class Meta:
        verbose_name = "Продажа"
        verbose_name_plural = "Продажи"
        ordering = ["-created_at"]

    def __str__(self):
        mark = " (СТОРНО)" if self.is_reversed else ""
        return f"Продажа #{self.pk} — {self.get_payment_type_display()} — {self.total}{mark}"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.payment_type == self.PaymentType.DEBT and not self.client_id:
            raise ValidationError({"client": "Для реализации (долга) нужно указать клиента."})


class SaleItem(models.Model):
    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name="items", verbose_name="Продажа"
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="sale_items",
        verbose_name="Товар",
    )
    packs = models.PositiveIntegerField("Количество, фасовок")
    price_per_unit = models.DecimalField(
        "Цена за штуку", max_digits=12, decimal_places=2,
        help_text="Цена за базовую единицу (штуку). У разных клиентов разная.",
    )
    cogs = models.DecimalField(
        "Себестоимость (FIFO)", max_digits=14, decimal_places=2, default=0, editable=False
    )
    # Выручка позиции — СНИМОК на момент продажи, как и себестоимость.
    # Пересчитывать её из packs × units_per_pack × price нельзя: units_per_pack
    # берётся из справочника ТЕКУЩЕГО товара, и стоит поправить фасовку —
    # вся прошлая выручка молча меняется. Для импортированных строк сюда
    # кладётся готовая сумма из таблицы заказчика.
    revenue = models.DecimalField(
        "Выручка позиции", max_digits=14, decimal_places=2, default=0, editable=False
    )

    class Meta:
        verbose_name = "Позиция продажи"
        verbose_name_plural = "Позиции продажи"

    def __str__(self):
        return f"{self.product} × {self.packs} {self.product.pack_name}"

    @property
    def base_quantity(self) -> int:
        return self.packs * self.product.units_per_pack

    @property
    def line_total(self) -> Decimal:
        return Decimal(self.base_quantity) * self.price_per_unit

    @property
    def profit(self) -> Decimal:
        return self.line_total - self.cogs
