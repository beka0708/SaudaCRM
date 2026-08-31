"""sales: продажа (Sale) и её позиции (SaleItem).

Продажа — «документ»: после проведения не редактируется. Списание склада и
создание долга/реализации выполняет sales.services.process_sale() в одной
транзакции (вызывается из админки/бота).
"""
from decimal import Decimal

from django.db import models


class Sale(models.Model):
    class PaymentType(models.TextChoices):
        CASH = "cash", "Наличные"
        # «Реализация» = денежный долг: клиент взял товар, должен сумму и гасит
        # её деньгами (объединили бывшие «в долг» и «под реализацию»).
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
        "Тип оплаты",
        max_length=16,
        choices=PaymentType.choices,
        default=PaymentType.CASH,
    )
    total = models.DecimalField(
        "Сумма продажи", max_digits=12, decimal_places=2, default=0, editable=False
    )
    comment = models.CharField("Комментарий", max_length=255, blank=True)
    is_processed = models.BooleanField("Проведена", default=False, editable=False)
    created_at = models.DateTimeField("Дата продажи", auto_now_add=True)

    class Meta:
        verbose_name = "Продажа"
        verbose_name_plural = "Продажи"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Продажа #{self.pk} — {self.get_payment_type_display()} — {self.total}"

    def clean(self):
        from django.core.exceptions import ValidationError

        # Реализация (долг) невозможна без клиента.
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
    packaging = models.ForeignKey(
        "catalog.PackagingUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Фасовка",
        help_text="Пусто = количество в базовых единицах.",
    )
    count = models.DecimalField(
        "Количество",
        max_digits=12,
        decimal_places=3,
        help_text="Сколько выбранных фасовок (или базовых единиц).",
    )
    base_quantity = models.DecimalField(
        "В базовых ед.", max_digits=12, decimal_places=3, editable=False, default=0
    )
    price = models.DecimalField(
        "Цена за ед.",
        max_digits=12,
        decimal_places=2,
        default=0,
        blank=True,
        help_text="За базовую единицу. Пусто → возьмём отпускную цену товара.",
    )

    class Meta:
        verbose_name = "Позиция продажи"
        verbose_name_plural = "Позиции продажи"

    def __str__(self):
        return f"{self.product} × {self.count}"

    @property
    def line_total(self) -> Decimal:
        return self.base_quantity * self.price

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.packaging_id and self.product_id and self.packaging.product_id != self.product_id:
            raise ValidationError({"packaging": "Эта фасовка принадлежит другому товару."})

    def save(self, *args, **kwargs):
        from apps.catalog.services import to_base_units

        self.base_quantity = to_base_units(self.product, self.count, self.packaging)
        if not self.price:
            self.price = self.product.sale_price
        super().save(*args, **kwargs)
