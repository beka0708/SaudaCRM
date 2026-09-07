"""Страница «Аналитика» — отдельная admin-страница (тяжёлая аналитика).

Собирает контекст ТОЛЬКО из apps.analytics.services. Рендерится внутри
админ-оболочки Unfold (сайдбар/шапка) через each_context.
"""
from datetime import date, timedelta

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.template.response import TemplateResponse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.catalog.services import fmt_qty

from . import services as s


def _parse(value, default):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def _title(icon, text, color="#10b981"):
    return format_html(
        '<span class="material-symbols-outlined" style="font-size:18px;vertical-align:-4px;'
        'margin-right:6px;color:{}">{}</span>{}', color, icon, text)


def _delta(current, previous):
    pct = s.pct_change(current, previous)
    if pct is None:
        return mark_safe('<span style="color:#9ca3af">—</span>')
    up = pct >= 0
    color = "#059669" if up else "#dc2626"
    arrow = "↑" if up else "↓"
    return format_html('<span style="color:{};font-weight:700">{} {}%</span>', color, arrow, abs(round(pct)))


def _minibar(value_str, pct, color="#94a3b8"):
    pct = min(100, max(0, pct))
    return format_html(
        '<div class="sd-mb"><span class="sd-mb-track"><span class="sd-mb-fill progress-bar-fill" '
        'data-width="{}" style="width:0;background:{}"></span></span><span class="sd-mb-val">{}</span></div>',
        pct, color, value_str)


def _product_link(pid, name):
    return format_html('<a href="/admin/catalog/product/{}/change/" class="sd-link">{}</a>', pid, name)


def _client_link(cid, name):
    return format_html('<a href="/admin/clients/client/{}/change/" class="sd-link">{}</a>', cid, name)


@staff_member_required
def analytics_view(request):
    # Произвольный период (по умолчанию — последние 30 дней).
    end = _parse(request.GET.get("end"), s.today())
    start = _parse(request.GET.get("start"), s.today() - timedelta(days=29))
    if start > end:
        start, end = end, start
    period_label = f"{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}"

    context = admin.site.each_context(request)

    # --- сравнение периодов (+ Δ колонка) ---
    cmp = s.month_comparison()
    cur, prev = cmp["current"], cmp["previous"]
    comparison_table = {
        "headers": ["Показатель", "Текущий месяц", "Прошлый месяц", "Δ"],
        "rows": [
            ["Продажи", s.money(cur["sales"]), s.money(prev["sales"]), _delta(cur["sales"], prev["sales"])],
            ["Прибыль", s.money(cur["profit"]), s.money(prev["profit"]), _delta(cur["profit"], prev["profit"])],
            ["Средний чек", s.money(cur["avg_check"]), s.money(prev["avg_check"]), _delta(cur["avg_check"], prev["avg_check"])],
            ["Число продаж", str(cur["count"]), str(prev["count"]), _delta(cur["count"], prev["count"])],
        ],
    }

    # --- маржинальность (bar пропорционально МАКСИМУМУ в списке — как в др. таблицах) ---
    margins = s.margin_by_product(start, end)
    max_margin = max((r["pct"] for r in margins), default=0) or 1
    margin_rows = []
    for r in margins:
        pct = round(r["pct"])
        bar = round(r["pct"] / max_margin * 100)
        margin_rows.append([_product_link(r["id"], r["name"]), s.money(r["profit"]), _minibar(f"{pct}%", bar)])
    margin_table = {"headers": ["Товар", "Прибыль", "Маржа"], "rows": margin_rows}

    # --- медленно продаваемые ---
    slow_table = {
        "headers": ["Товар", "Продано за период", "Остаток"],
        "rows": [[_product_link(r["id"], r["name"]), f"{fmt_qty(r['qty_sold'])} шт", f"{fmt_qty(r['stock'])} шт"]
                 for r in s.slow_movers(start, end)],
    }

    # --- прогноз запаса (3 уровня: <7 красный, 7–30 оранжевый, >30 обычный) ---
    forecast_rows = []
    for r in s.stock_forecast(start, end):
        dl = r["days_left"]
        if dl is None:
            cell = "—"
        elif dl < 7:
            cell = format_html('<span style="color:#dc2626;font-weight:700">{} дн</span>', dl)
        elif dl <= 30:
            cell = format_html('<span style="color:#d97706;font-weight:600">{} дн</span>', dl)
        else:
            cell = f"{dl} дн"
        forecast_rows.append([_product_link(r["id"], r["name"]), f"{fmt_qty(r['stock'])} шт", cell])
    forecast_table = {"headers": ["Товар", "Остаток", "Хватит на"], "rows": forecast_rows}

    # --- топ должников (bar оранжевый — долги) ---
    debtors, _ = s.top_debtors()
    max_debt = max((r["debt"] for r in debtors), default=0) or 1
    debtor_rows = []
    for r in debtors:
        pct = round(float(r["debt"] / max_debt * 100))
        debtor_rows.append([_client_link(r["id"], r["name"]), _minibar(s.money(r["debt"]), pct, "#f59e0b")])
    debtors_table = {"headers": ["Клиент", "Долг"], "rows": debtor_rows}

    # --- топ клиентов по объёму закупок (bar синий — не путать с долгами) ---
    buyers = s.top_clients_by_purchase(start, end)
    max_buy = max((r["total"] for r in buyers), default=0) or 1
    buyer_rows = []
    for r in buyers:
        pct = round(float(r["total"] / max_buy * 100))
        buyer_rows.append([_client_link(r["id"], r["name"]), _minibar(s.money(r["total"]), pct, "#3b82f6")])
    buyers_table = {"headers": ["Клиент", "Закупки за период"], "rows": buyer_rows}

    context.update({
        "title": "Аналитика",
        "an_start": start.isoformat(),
        "an_end": end.isoformat(),
        "an_period_label": period_label,
        "comparison_title": _title("compare_arrows", "Текущий месяц vs прошлый", "#3b82f6"),
        "margin_title": _title("percent", "Маржинальность (за период)", "#10b981"),
        "forecast_title": _title("hourglass_empty", "Прогноз запаса (за период)", "#f59e0b"),
        "slow_title": _title("trending_down", "Медленно продаваемые (за период)", "#ef4444"),
        "debtors_title": _title("groups", "ТОП должников (сейчас)", "#f59e0b"),
        "buyers_title": _title("shopping_cart", "ТОП клиентов (за период)", "#3b82f6"),
        "comparison_table": comparison_table,
        "margin_table": margin_table,
        "slow_table": slow_table,
        "forecast_table": forecast_table,
        "debtors_table": debtors_table,
        "buyers_table": buyers_table,
    })
    return TemplateResponse(request, "admin/analytics.html", context)
