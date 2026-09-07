"""Админка раздела «catalog»."""
from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from .models import PackagingUnit, Product
from .services import stock_breakdown


class PackagingUnitInline(TabularInline):
    model = PackagingUnit
    extra = 1
    verbose_name = "Фасовка"
    verbose_name_plural = "Фасовки (блок, коробка и т.п.)"


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = (
        "name",
        "stock_display",
        "cost_price",
        "sale_price",
        "margin_display",
        "is_active",
    )
    list_filter = ("is_active",)
    search_fields = ("name",)
    inlines = [PackagingUnitInline]

    def get_queryset(self, request):
        # Аннотируем остаток одним запросом, чтобы не дёргать БД по строке.
        return super().get_queryset(request).annotate(_stock=Sum("movements__quantity"))

    @admin.display(description="Остаток", ordering="_stock")
    def stock_display(self, obj):
        stock = obj._stock or 0
        # Разбивка по фасовкам: «1 коробка + 5 шт».
        human = stock_breakdown(obj, stock)
        if stock < obj.low_stock_threshold:
            # Низкий остаток — подсвечиваем красным + значок.
            return format_html(
                '<span style="color:#dc2626;font-weight:600">⚠ {}</span>', human
            )
        return human

    @admin.display(description="Маржа/ед.")
    def margin_display(self, obj):
        return obj.margin

    @admin.action(description="Экспорт остатков в Excel")
    def export_xlsx(self, request, queryset):
        from apps.reports.services import single_sheet_response

        rows = [
            [p.name, p.base_unit, float(p._stock or 0), float(p.cost_price),
             float((p._stock or 0) * p.cost_price)]
            for p in queryset
        ]
        return single_sheet_response(
            "stock.xlsx", "Остатки",
            ["Товар", "Ед.", "Остаток", "Себестоимость", "Стоимость"], rows, money_cols=(4, 5))

    actions = ["export_xlsx"]
