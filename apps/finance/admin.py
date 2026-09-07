"""Админка раздела «finance»."""
from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import CashFlow


@admin.register(CashFlow)
class CashFlowAdmin(ModelAdmin):
    list_display = ("date", "direction_display", "category", "amount", "comment")
    list_filter = ("direction", "category", "date")
    search_fields = ("comment",)
    date_hierarchy = "date"
    autocomplete_fields = ("sale", "debt_payment")
    readonly_fields = ("created_at",)

    @admin.display(description="Тип", ordering="direction")
    def direction_display(self, obj):
        color = "#16a34a" if obj.direction == CashFlow.Direction.IN else "#dc2626"
        return format_html(
            '<span style="color:{};font-weight:600">{}</span>',
            color,
            obj.get_direction_display(),
        )

    @admin.action(description="Экспорт в Excel")
    def export_xlsx(self, request, queryset):
        from apps.reports.services import single_sheet_response

        rows = [
            [c.date.strftime("%d.%m.%Y"), c.get_direction_display(),
             c.get_category_display(), float(c.amount), c.comment]
            for c in queryset
        ]
        return single_sheet_response(
            "cashflow.xlsx", "Касса",
            ["Дата", "Тип", "Категория", "Сумма", "Комментарий"], rows, money_cols=(4,))

    actions = ["export_xlsx"]
