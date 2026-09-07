"""Админка раздела «sales»."""
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import Sale, SaleItem
from .services import process_sale


class SaleItemInline(TabularInline):
    model = SaleItem
    extra = 1
    autocomplete_fields = ("product",)
    readonly_fields = ("base_quantity",)

    # После проведения продажи позиции не редактируем (obj = родительская Sale).
    def has_add_permission(self, request, obj):
        return obj is None or not obj.is_processed

    def has_change_permission(self, request, obj=None):
        return obj is None or not obj.is_processed

    def has_delete_permission(self, request, obj=None):
        return obj is None or not obj.is_processed


@admin.register(Sale)
class SaleAdmin(ModelAdmin):
    list_display = ("id", "created_at", "client", "payment_type", "total", "is_processed")
    list_filter = ("payment_type", "created_at")
    search_fields = ("client__name", "comment")
    autocomplete_fields = ("client",)
    date_hierarchy = "created_at"
    inlines = [SaleItemInline]

    def get_readonly_fields(self, request, obj=None):
        base = ("total", "is_processed", "created_at")
        # Проведённая продажа — «документ», шапку тоже не редактируем.
        if obj is not None and obj.is_processed:
            return base + ("client", "payment_type", "comment")
        return base

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Позиции уже сохранены (base_quantity посчитан) — проводим продажу.
        process_sale(form.instance)

    @admin.action(description="Экспорт в Excel")
    def export_xlsx(self, request, queryset):
        from apps.reports.services import single_sheet_response

        rows = [
            [s.created_at.strftime("%d.%m.%Y"), str(s.client) if s.client else "—",
             s.get_payment_type_display(), float(s.total)]
            for s in queryset.select_related("client")
        ]
        return single_sheet_response(
            "sales.xlsx", "Продажи", ["Дата", "Клиент", "Тип оплаты", "Сумма"], rows, money_cols=(4,))

    actions = ["export_xlsx"]