"""Админка раздела «finance»."""
from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from apps.core.admin import LedgerDocumentMixin

from .models import CashFlow, Obligation, ObligationPayment, RecurringExpense


@admin.register(RecurringExpense)
class RecurringExpenseAdmin(ModelAdmin):
    """Шаблоны ежемесячных расходов. Проводит их команда post_recurring из cron.

    Удалять можно: это настройка, а не документ. Уже проведённые расходы
    останутся в кассе — у CashFlow.recurring стоит SET_NULL.
    """

    list_display = ("name", "amount", "category", "day_display", "is_active", "last_posted")
    list_editable = ("amount", "is_active")
    list_filter = ("is_active", "category")
    readonly_fields = ("created_at",)

    @admin.display(description="День проведения")
    def day_display(self, obj):
        return obj.day or "последний день месяца"

    @admin.display(description="Последний раз проведён")
    def last_posted(self, obj):
        flow = obj.postings.order_by("-date").first()
        return flow.date.strftime("%d.%m.%Y") if flow else "—"


@admin.register(CashFlow)
class CashFlowAdmin(LedgerDocumentMixin, ModelAdmin):
    list_display = ("date", "direction_display", "category", "subcategory", "amount", "comment")
    list_filter = ("direction", "category", "subcategory", "date")
    search_fields = ("comment", "subcategory")
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


class ObligationPaymentInline(LedgerDocumentMixin, TabularInline):
    model = ObligationPayment
    extra = 0
    fields = ("created_at", "amount", "rate", "comment", "is_reversed")
    readonly_fields = ("is_reversed",)


@admin.register(Obligation)
class ObligationAdmin(ModelAdmin):
    """Наши долги: кредиты и заёмы. Остаток считается из платежей."""

    list_display = ("name", "currency", "remaining_display", "remaining_kgs_display",
                    "default_payment", "payment_day", "is_active")
    list_editable = ("payment_day",)
    list_filter = ("currency", "is_active")
    inlines = [ObligationPaymentInline]
    readonly_fields = ("created_at",)

    @admin.display(description="Остаток")
    def remaining_display(self, obj):
        return f"{obj.remaining:,.0f} {obj.currency}".replace(",", " ")

    @admin.display(description="Остаток, сом")
    def remaining_kgs_display(self, obj):
        return f"{obj.remaining_kgs:,.0f}".replace(",", " ")


@admin.register(ObligationPayment)
class ObligationPaymentAdmin(LedgerDocumentMixin, ModelAdmin):
    """Платежи по нашим долгам — документ, удалять нельзя (деньги уже ушли)."""

    list_display = ("created_at", "obligation", "amount", "rate", "status", "comment")
    list_filter = ("obligation", "is_reversed")
    search_fields = ("comment",)
    date_hierarchy = "created_at"

    @admin.display(description="Статус")
    def status(self, obj):
        if obj.is_reversed:
            return format_html('<span style="color:#dc2626;font-weight:600">СТОРНО</span>')
        return "—"

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return ("obligation", "amount", "rate", "created_at",
                "is_reversed", "reversed_at", "reversed_by", "reversal_reason")
