"""warehouse: партионный учёт (FIFO).

Каждый приход = отдельная ПАРТИЯ со своей себестоимостью и своим остатком.
Остаток товара = сумма остатков партий (в фасовках). При продаже партии
расходуются по FIFO (старые первыми) — так себестоимость каждой продажи
берётся из реально «съеденной» партии. Приход партии автоматически книжит
расход «Закупка» в кассу.
"""
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.core.models import ReversibleDocument


class Batch(ReversibleDocument):
    """Партия прихода товара.

    Сторнированная партия обнуляет `packs_remaining`, поэтому автоматически
    выпадает и из остатка (`get_stock`), и из FIFO, и из стоимости склада —
    отдельных фильтров по `is_reversed` для склада не нужно.
    """

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="batches",
        verbose_name="Товар",
    )
    cost_per_unit = models.DecimalField(
        "Себестоимость за шт", max_digits=12, decimal_places=2
    )
    packs_received = models.PositiveIntegerField("Приход, фасовок")
    packs_remaining = models.PositiveIntegerField(
        "Остаток, фасовок", default=0, editable=False
    )
    comment = models.CharField("Комментарий", max_length=255, blank=True)
    # НЕ auto_now_add: приход нужно уметь оприходовать задним числом (импорт
    # истории, забытая накладная). Дата партии задаёт и порядок FIFO, и дату
    # расхода «Закупка» в кассе.
    created_at = models.DateTimeField(
        "Дата прихода",
        default=timezone.now,
        help_text="По умолчанию — сейчас. Можно указать прошедшую дату.",
    )

    class Meta:
        verbose_name = "Партия (приход)"
        verbose_name_plural = "Партии / приходы"
        ordering = ["created_at"]  # FIFO: старые партии расходуются первыми
        indexes = [models.Index(fields=["product", "created_at"])]

    def __str__(self):
        mark = " (СТОРНО)" if self.is_reversed else ""
        return (
            f"{self.product} — партия по {self.cost_per_unit} "
            f"({self.packs_remaining}/{self.packs_received}){mark}"
        )

    @property
    def units_remaining(self) -> int:
        return self.packs_remaining * self.product.units_per_pack

    @property
    def remaining_value(self) -> Decimal:
        return Decimal(self.units_remaining) * self.cost_per_unit

    def save(self, *args, **kwargs):
        creating = self.pk is None
        if creating:
            self.packs_remaining = self.packs_received
        super().save(*args, **kwargs)
        # Приход = авто-расход «Закупка» в кассу (единая точка: и админка, и сервис).
        if creating:
            from apps.finance.models import CashFlow
            from apps.finance.services import add_expense

            amount = Decimal(self.packs_received * self.product.units_per_pack) * self.cost_per_unit
            add_expense(
                CashFlow.Category.PURCHASE,
                amount,
                # Дата расхода = дата партии, иначе приход задним числом ляжет
                # в кассу сегодняшним днём и отчёты за период разъедутся.
                date=timezone.localdate(self.created_at),
                comment=self.comment
                or f"Закупка: {self.product} ({self.packs_received} {self.product.pack_name})",
            )


class BatchConsumption(models.Model):
    """Списание из партии при продаже — для расчёта COGS и истории."""

    sale_item = models.ForeignKey(
        "sales.SaleItem",
        on_delete=models.CASCADE,
        related_name="consumptions",
        verbose_name="Позиция продажи",
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, related_name="consumptions", verbose_name="Партия"
    )
    packs = models.PositiveIntegerField("Списано, фасовок")
    cost_per_unit = models.DecimalField(
        "Себестоимость за шт (снимок)", max_digits=12, decimal_places=2
    )
    # Проставляется датой продажи (consume_fifo), чтобы история списаний
    # совпадала с датой документа при проведении задним числом.
    created_at = models.DateTimeField("Дата", default=timezone.now)

    class Meta:
        verbose_name = "Списание из партии"
        verbose_name_plural = "Списания из партий"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.batch}: −{self.packs}"
