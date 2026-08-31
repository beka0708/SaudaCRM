"""catalog: справочник товаров, фасовки и цены.

Остаток товара НЕ хранится в этой модели — он считается из движений склада (apps.warehouse).
Здесь только справочные данные: цена, себестоимость, фасовки.
"""
from decimal import Decimal
from django.db import models


class Product(models.Model):
    name = models.CharField("Наименование", max_length=255, unique=True)
    base_unit = models.CharField(
        "Базовая единица",
        max_length=32,
        default="шт",
        help_text="Наименьшая единица учёта (шт, кг, л). В ней считается остаток.",
    )
    cost_price = models.DecimalField(
        "Себестоимость (за ед.)", max_digits=12, decimal_places=2, default=0
    )
    sale_price = models.DecimalField(
        "Отпускная цена (за ед.)", max_digits=12, decimal_places=2, default=0
    )
    low_stock_threshold = models.DecimalField(
        "Порог низкого остатка",
        max_digits=12,
        decimal_places=3,
        default=0,
        help_text="Если остаток опустится ниже — товар попадёт в список на пополнение.",
    )
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def stock(self) -> Decimal:
        """Текущий остаток в базовых единицах (из движений склада)."""
        from apps.warehouse.services import get_stock

        return get_stock(self)

    @property
    def margin(self) -> Decimal:
        """Маржа за единицу (отпускная цена − себестоимость)."""
        return self.sale_price - self.cost_price

    @property
    def is_low_stock(self) -> bool:
        return self.stock < self.low_stock_threshold

    @property
    def stock_breakdown(self) -> str:
        """Остаток, разбитый по фасовкам: напр. «1 коробка + 5 шт»."""
        from apps.catalog.services import stock_breakdown

        return stock_breakdown(self)


class PackagingUnit(models.Model):
    """Фасовка товара: например, блок = 12 шт, коробка = 96 шт.

    Базовая единица (=1) подразумевается автоматически и здесь не хранится.
    Позволяет приходовать/продавать «1 коробку», а система сама пересчитает
    это в базовые единицы (шт).
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="packagings",
        verbose_name="Товар",
    )
    name = models.CharField(
        "Название фасовки", max_length=64, help_text="Напр.: блок, коробка, упаковка"
    )
    quantity_in_base = models.DecimalField(
        "Базовых единиц в фасовке",
        max_digits=12,
        decimal_places=3,
        help_text="Сколько базовых единиц в одной такой упаковке. Напр.: коробка = 96.",
    )

    class Meta:
        verbose_name = "Фасовка"
        verbose_name_plural = "Фасовки"
        unique_together = [("product", "name")]

    def __str__(self):
        return f"{self.product.name}: {self.name} = {self.quantity_in_base} {self.product.base_unit}"

    def to_base(self, count) -> Decimal:
        """Перевести count таких фасовок в базовые единицы."""
        return Decimal(str(count)) * self.quantity_in_base
