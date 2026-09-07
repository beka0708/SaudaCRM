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

    @admin.action(description="Экспорт в Excel")
    def export_xlsx(self, request, queryset):
        from apps.reports.services import single_sheet_response

        rows = [
            [str(d.client), float(d.amount), float(d.paid), float(d.remaining),
             d.created_at.strftime("%d.%m.%Y")]
            for d in queryset.select_related("client")
        ]
        return single_sheet_response(
            "debts.xlsx", "Долги",
            ["Клиент", "Сумма долга", "Оплачено", "Остаток", "Дата"], rows, money_cols=(2, 3, 4))

    actions = ["export_xlsx"]


@admin.register(DebtPayment)
class DebtPaymentAdmin(ModelAdmin):
    list_display = ("created_at", "debt", "amount", "comment")
    search_fields = ("debt__client__name", "comment")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)