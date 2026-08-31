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