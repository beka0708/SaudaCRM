"""Страница «Отчёты»: выбор периода и скачивание сводного Excel."""
from datetime import date

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.template.response import TemplateResponse

from apps.analytics.services import money, month_start, monthly_breakdown, today

from . import services


def _parse(value, default):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


@staff_member_required
def reports_view(request):
    default_start = month_start()
    default_end = today()

    if request.GET.get("download"):
        start = _parse(request.GET.get("start"), default_start)
        end = _parse(request.GET.get("end"), default_end)
        return services.build_period_response(start, end)

    # «Анализ наших работ» — помесячная сводка как в Excel у заказчика.
    # Живёт здесь, а не в Аналитике: колонок одиннадцать, и на странице
    # с другими таблицами она не помещалась и не прокручивалась.
    monthly = [r for r in monthly_breakdown(12) if r["revenue"] or r["expenses"]]
    monthly_rows = [{
        "label": r["label"],
        "cells": [
            money(r["revenue"]), money(r["cogs"]), money(r["expenses"]),
            money(r["profit"]), money(r["sold_debt"]), money(r["returned"]),
            f"{r['pct_expenses']:.2f}%", f"{r['pct_margin']:.2f}%",
            f"{r['pct_returned']:.2f}%", f"{r['pct_debt']:.2f}%",
        ],
        "profit_negative": r["profit"] < 0,
    } for r in monthly]

    context = admin.site.each_context(request)
    context.update({
        "title": "Отчёты",
        "monthly_headers": [
            "Месяц", "Выручка", "Себестоимость", "Расходы", "Чистый доход",
            "Продано под реал", "Вернули", "% расх", "% рентаб",
            "% возвр", "% под реал",
        ],
        "monthly_rows": monthly_rows,
        "default_start": request.GET.get("start", default_start.isoformat()),
        "default_end": request.GET.get("end", default_end.isoformat()),
    })
    return TemplateResponse(request, "admin/reports.html", context)
