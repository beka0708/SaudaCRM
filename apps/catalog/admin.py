"""Админка раздела «catalog»."""
from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import Product
from .services import stock_breakdown


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = ("name", "pack_name", "units_per_pack", "stock_display", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    fields = ("name", "base_unit", "pack_name", "units_per_pack", "low_stock_threshold", "is_active")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_stock=Sum("batches__packs_remaining"))

    @admin.display(description="Остаток", ordering="_stock")
    def stock_display(self, obj):
        packs = obj._stock or 0
        human = stock_breakdown(obj, packs)
        if obj.low_stock_threshold and packs < obj.low_stock_threshold:
            return format_html('<span style="color:#dc2626;font-weight:600">⚠ {}</span>', human)
        return human

    @admin.action(description="Экспорт остатков в Excel")
    def export_xlsx(self, request, queryset):
        from apps.reports.services import single_sheet_response
        from apps.warehouse.services import stock_value

        rows = []
        for p in queryset:
            packs = getattr(p, "_stock", None)
            packs = p.stock if packs is None else packs
            rows.append([p.name, p.pack_name, int(packs or 0), p.units_per_pack, float(stock_value(p))])
        return single_sheet_response(
            "stock.xlsx", "Остатки",
            ["Товар", "Фасовка", "Остаток (фасовок)", "Штук в фасовке", "Стоимость"],
            rows, money_cols=(5,))

    actions = ["export_xlsx"]
