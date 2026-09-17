"""catalog: справочник товаров.

Одна фасовка на товар (pack_name + units_per_pack). Продают ТОЛЬКО фасовками.
Себестоимость — не тут, а по партиям (apps.warehouse.Batch, FIFO). Отпускной
цены у товара нет — её вводят при продаже (у разных клиентов разная).
Остаток товара считается из партий (в фасовках).
"""
from django.db import models


class Product(models.Model):
    name = models.CharField("Наименование", max_length=255, unique=True)
    base_unit = models.CharField(
        "Базовая единица",
        max_length=32,
        default="шт",
        help_text="Единица внутри фасовки (шт, кг). Цена/себестоимость — за неё.",
    )
    pack_name = models.CharField(
        "Фасовка",
        max_length=64,
        default="коробка",
        help_text="Как называется фасовка: коробка, блок, мешок…",
    )
    units_per_pack = models.PositiveIntegerField(
        "Штук в фасовке",
        default=1,
        help_text="Сколько базовых единиц в одной фасовке (напр. коробка = 96).",
    )
    low_stock_threshold = models.PositiveIntegerField(
        "Порог низкого остатка (фасовок)",
        default=0,
        help_text="Если остаток в фасовках ниже — товар попадёт на пополнение.",
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
    def stock(self) -> int:
        """Текущий остаток В ФАСОВКАХ (сумма остатков партий)."""
        from apps.warehouse.services import get_stock

        return get_stock(self)

    @property
    def is_low_stock(self) -> bool:
        return self.low_stock_threshold > 0 and self.stock < self.low_stock_threshold

    @property
    def stock_breakdown(self) -> str:
        """Остаток в фасовках: напр. «5 коробок (480 шт)»."""
        from apps.catalog.services import stock_breakdown

        return stock_breakdown(self)
