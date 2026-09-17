"""Админка раздела «debts»."""
from django.contrib import admin, messages
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from apps.core.admin import LedgerDocumentMixin

from .models import Debt, DebtPayment
from .services import reverse_debt_payment


class DebtPaymentInline(LedgerDocumentMixin, TabularInline):
    model = DebtPayment
    extra = 0


@admin.register(Debt)
class DebtAdmin(LedgerDocumentMixin, ModelAdmin):
    list_display = ("client", "amount", "paid_display", "remaining_display", "created_at")
    list_filter = ("client",)
    search_fields = ("client__name", "comment")
    autocomplete_fields = ("client",)
    date_hierarchy = "created_at"
    inlines = [DebtPaymentInline]

    def get_readonly_fields(self, request, obj=None):
        # Дату возникновения задаём только при создании (обычно долг заводит
        # продажа и наследует её дату).
        return ("created_at",) if obj is not None else ()

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
class DebtPaymentAdmin(LedgerDocumentMixin, ModelAdmin):
    list_display = ("created_at", "debt", "amount", "status", "comment")
    list_filter = ("is_reversed",)
    search_fields = ("debt__client__name", "comment")
    date_hierarchy = "created_at"

    @admin.display(description="Статус", ordering="is_reversed")
    def status(self, obj):
        if obj.is_reversed:
            return format_html('<span style="color:#dc2626;font-weight:600">СТОРНО</span>')
        return "—"

    def get_readonly_fields(self, request, obj=None):
        # Дату оплаты задаём при создании (можно принять «вчерашним числом»);
        # после — она уже отражена в дате прихода в кассе.
        if obj is None:
            return ()
        base = ("created_at",)
        if obj.is_reversed:
            base += ("is_reversed", "reversed_at", "reversed_by", "reversal_reason")
        return base

    @admin.action(description="Сторнировать (отменить оплату)")
    def reverse_action(self, request, queryset):
        """Отмена ошибочно принятой оплаты: деньги обратно, долг снова открыт."""
        done = 0
        for payment in queryset:
            reverse_debt_payment(payment, user=request.user, reason="Сторно из админки")
            done += 1
        self.message_user(
            request, f"Сторнировано оплат: {done}", level=messages.SUCCESS
        )

    actions = ["reverse_action"]