"""Админка раздела «debts»."""
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import Debt, DebtPayment


class DebtPaymentInline(TabularInline):
    model = DebtPayment
    extra = 0


@admin.register(Debt)
class DebtAdmin(ModelAdmin):
    list_display = ("client", "amount", "paid_display", "remaining_display", "created_at")
    list_filter = ("client",)
    search_fields = ("client__name", "comment")
    autocomplete_fields = ("client",)
    date_hierarchy = "created_at"
    inlines = [DebtPaymentInline]
    readonly_fields = ("created_at",)

    @admin.display(description="Оплачено")
    def paid_display(self, obj):
        return obj.paid

    @admin.display(description="Остаток")
    def remaining_display(self, obj):
        return obj.remaining


@admin.register(DebtPayment)
class DebtPaymentAdmin(ModelAdmin):
    list_display = ("created_at", "debt", "amount", "comment")
    search_fields = ("debt__client__name", "comment")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)