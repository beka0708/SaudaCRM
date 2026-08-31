"""Админка раздела «warehouse»."""
from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.catalog.services import fmt_qty

from .models import Receipt, StockMovement


@admin.register(Receipt)
class ReceiptAdmin(ModelAdmin):
    """Приход партии: выбираешь товар + фасовку + количество — остальное авто."""

    list_display = ("created_at", "product", "packaging", "count", "base_display", "comment")
    list_filter = ("product",)
    search_fields = ("product__name", "comment")
    date_hierarchy = "created_at"
    autocomplete_fields = ("product",)

    @admin.display(description="Итого")
    def base_display(self, obj):
        return f"{fmt_qty(obj.base_quantity)} {obj.product.base_unit}"

    def get_readonly_fields(self, request, obj=None):
        base = ("base_quantity", "movement", "created_at")
        # Приход — «документ»: после создания его поля не редактируем,
        # чтобы складское движение не рассогласовалось с приходом.
        if obj is not None:
            return base + ("product", "packaging", "count", "comment")
        return base


@admin.register(StockMovement)
class StockMovementAdmin(ModelAdmin):
    """Сырой журнал движений (машинное отделение) — история и ручные корректировки."""

    list_display = ("created_at", "product", "movement_type", "quantity", "comment")
    list_filter = ("movement_type", "product")
    search_fields = ("product__name", "comment")
    date_hierarchy = "created_at"
    autocomplete_fields = ("product",)
    readonly_fields = ("created_at",)
