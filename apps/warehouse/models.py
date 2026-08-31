"""warehouse: журнал складских движений.

Ключевой принцип: остаток товара нигде не хранится числом, а всегда считается
как сумма движений (event-sourcing). Это даёт полную историю и аудит «бесплатно».
"""
from django.db import models


class StockMovement(models.Model):
    class Type(models.TextChoices):
        RECEIPT = "receipt", "Приход"
        SALE = "sale", "Продажа"
        ADJUSTMENT = "adjustment", "Корректировка"

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="movements",
        verbose_name="Товар",
    )
    movement_type = models.CharField(
        "Тип движения", max_length=16, choices=Type.choices
    )
    quantity = models.DecimalField(
        "Количество (± базовых ед.)",
        max_digits=12,
        decimal_places=3,
        help_text="Со знаком: приход +, продажа −. Остаток = сумма всех движений.",
    )
    comment = models.CharField("Комментарий", max_length=255, blank=True)
    created_at = models.DateTimeField("Дата", auto_now_add=True)

    class Meta:
        verbose_name = "Складское движение"
        verbose_name_plural = "Складские движения"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["product", "created_at"])]

    def __str__(self):
        return f"{self.get_movement_type_display()}: {self.product} {self.quantity:+}"


class Receipt(models.Model):
    """Приход партии — удобный «документ» поступления товара.

    Пользователь указывает товар, фасовку (блок/коробка) и количество этих
    фасовок. При сохранении система сама пересчитывает всё в базовые единицы,
    ставит знак «+» и создаёт складское движение (StockMovement типа «Приход»).
    Так на складе не нужно считать 96×2 в уме и вручную ставить знаки.
    """

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="receipts",
        verbose_name="Товар",
    )
    packaging = models.ForeignKey(
        "catalog.PackagingUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Фасовка",
        help_text="Пусто = количество указано в базовых единицах товара.",
    )
    count = models.DecimalField(
        "Количество",
        max_digits=12,
        decimal_places=3,
        help_text="Сколько выбранных фасовок (или базовых единиц, если фасовка не выбрана).",
    )
    base_quantity = models.DecimalField(
        "Итого в базовых единицах",
        max_digits=12,
        decimal_places=3,
        editable=False,
        default=0,
    )
    comment = models.CharField("Комментарий", max_length=255, blank=True)
    movement = models.OneToOneField(
        StockMovement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="receipt",
        verbose_name="Складское движение",
    )
    created_at = models.DateTimeField("Дата", auto_now_add=True)

    class Meta:
        verbose_name = "Приход партии"
        verbose_name_plural = "Приходы партий"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Приход: {self.product} ({self.count})"

    def clean(self):
        # Фасовка должна принадлежать выбранному товару.
        from django.core.exceptions import ValidationError

        if self.packaging_id and self.product_id and self.packaging.product_id != self.product_id:
            raise ValidationError({"packaging": "Эта фасовка принадлежит другому товару."})

    def save(self, *args, **kwargs):
        from apps.catalog.services import to_base_units

        from .services import receive_stock

        creating = self.pk is None
        self.base_quantity = to_base_units(self.product, self.count, self.packaging)
        super().save(*args, **kwargs)

        # Складское движение создаём один раз — при создании прихода.
        if creating:
            self.movement = receive_stock(
                self.product,
                self.base_quantity,
                self.comment or f"Приход партии #{self.pk}",
            )
            super().save(update_fields=["movement"])

    def delete(self, *args, **kwargs):
        movement = self.movement
        super().delete(*args, **kwargs)
        if movement is not None:
            movement.delete()
