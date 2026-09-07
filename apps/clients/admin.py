"""Админка раздела «clients»."""
from django.contrib import admin
from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin

from apps.analytics.services import money

from .models import Client

_DEC = DecimalField(max_digits=20, decimal_places=2)
_HISTORY_LIMIT = 50


@admin.register(Client)
class ClientAdmin(ModelAdmin):
    list_display = ("name", "phone", "address", "debt_display")
    search_fields = ("name", "phone", "address")
    readonly_fields = ("operations_history",)
    fieldsets = (
        (None, {"fields": ("name", "phone", "address", "comment")}),
        ("История операций", {"fields": ("operations_history",)}),
    )

    def get_queryset(self, request):
        # Долг клиента одним запросом через Subquery (без N+1):
        # Σ(суммы долгов) − Σ(оплаты долгов). Отдельные подзапросы, чтобы JOIN не
        # раздувал суммы.
        from apps.debts.models import Debt, DebtPayment

        debt_amount = (
            Debt.objects.filter(client=OuterRef("pk"))
            .values("client").annotate(s=Sum("amount")).values("s")
        )
        paid = (
            DebtPayment.objects.filter(debt__client=OuterRef("pk"))
            .values("debt__client").annotate(s=Sum("amount")).values("s")
        )
        return super().get_queryset(request).annotate(
            _debt=Coalesce(Subquery(debt_amount, output_field=_DEC), Value(0, output_field=_DEC))
            - Coalesce(Subquery(paid, output_field=_DEC), Value(0, output_field=_DEC))
        )

    @admin.display(description="Текущий долг", ordering="_debt")
    def debt_display(self, obj):
        # На списке берём аннотацию; если её нет (напр. detail) — свойство.
        debt = getattr(obj, "_debt", None)
        if debt is None:
            debt = obj.current_debt
        return f"{money(debt)} сом"

    @admin.display(description="")
    def operations_history(self, obj):
        if obj is None or obj.pk is None:
            return "—"

        from apps.debts.models import DebtPayment
        from apps.sales.models import Sale

        sales = list(
            Sale.objects.filter(client=obj).order_by("-created_at")[:_HISTORY_LIMIT]
        )
        payments = list(
            DebtPayment.objects.filter(debt__client=obj)
            .select_related("debt")
            .order_by("-created_at")[:_HISTORY_LIMIT]
        )

        events = []
        for s in sales:
            events.append({
                "dt": s.created_at, "kind": "Продажа", "color": "#3b82f6",
                "detail": s.get_payment_type_display(),
                "amount": s.total, "sign": "",
                "url": f"/admin/sales/sale/{s.pk}/change/",
            })
        for p in payments:
            events.append({
                "dt": p.created_at, "kind": "Оплата долга", "color": "#10b981",
                "detail": p.comment or f"долг #{p.debt_id}",
                "amount": p.amount, "sign": "−",
                "url": f"/admin/debts/debt/{p.debt_id}/change/",
            })
        events.sort(key=lambda e: e["dt"], reverse=True)
        events = events[:_HISTORY_LIMIT]

        if not events:
            return format_html('<div style="color:#9ca3af">Операций пока нет.</div>')

        # _debt — аннотация из get_queryset (get_object её тоже использует),
        # чтобы не считать current_debt через N+1.
        debt_val = getattr(obj, "_debt", None)
        if debt_val is None:
            debt_val = obj.current_debt
        summary = format_html(
            '<div style="margin-bottom:10px;font-size:13px;color:#6b7280">'
            'Покупок: <b>{}</b> · Оплат долга: <b>{}</b> · Текущий долг: '
            '<b style="color:#f59e0b">{} сом</b></div>',
            len(sales), len(payments), money(debt_val),
        )

        rows = format_html_join(
            "",
            '<tr>'
            '<td style="padding:7px 12px;border-top:1px solid #eee;white-space:nowrap">{}</td>'
            '<td style="padding:7px 12px;border-top:1px solid #eee">'
            '<a href="{}" style="color:{};font-weight:600;text-decoration:none">{}</a></td>'
            '<td style="padding:7px 12px;border-top:1px solid #eee;color:#6b7280">{}</td>'
            '<td style="padding:7px 12px;border-top:1px solid #eee;text-align:right;'
            'font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap">{}{} сом</td>'
            '</tr>',
            (
                (e["dt"].strftime("%d.%m.%Y %H:%M"), e["url"], e["color"], e["kind"],
                 e["detail"], e["sign"], money(e["amount"]))
                for e in events
            ),
        )

        note = ""
        if len(sales) == _HISTORY_LIMIT or len(payments) == _HISTORY_LIMIT:
            note = format_html(
                '<div style="margin-top:8px;font-size:11px;color:#9ca3af">'
                'Показаны последние операции (до {} каждого типа).</div>', _HISTORY_LIMIT)

        return format_html(
            '{}<table style="width:100%;border-collapse:collapse;font-size:13px">'
            '<thead><tr style="text-align:left;color:#6b7280;font-size:11px;'
            'text-transform:uppercase">'
            '<th style="padding:0 12px 6px">Дата</th><th style="padding:0 12px 6px">Операция</th>'
            '<th style="padding:0 12px 6px">Детали</th>'
            '<th style="padding:0 12px 6px;text-align:right">Сумма</th></tr></thead>'
            '<tbody>{}</tbody></table>{}',
            summary, rows, note,
        )
