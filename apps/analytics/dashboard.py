"""Сборка данных главного дашборда для Unfold (DASHBOARD_CALLBACK).

Тонкий слой: только собирает контекст из apps.analytics.services. Графики
«Выручка» и «Оплаты» рисуются своим скриптом в шаблоне (нужны градиенты —
их нельзя выразить в JSON), поэтому сюда кладём сырые числа для Chart.js.
Decimal → float только на самом выходе в JSON (JS не умеет Decimal).
"""
import json
from datetime import timedelta

from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.catalog.services import fmt_qty
from apps.finance.services import get_cash_balance, profit

from . import services as s


def _trend(current, previous):
    pct = s.pct_change(current, previous)
    if pct is None:
        return None
    return {"up": pct >= 0, "pct": abs(round(pct))}


def _minibar(value_str, pct, color="#10b981"):
    """Ячейка таблицы: тонкий progress-bar (заполняется анимацией) + число."""
    return format_html(
        '<div class="sd-mb"><span class="sd-mb-track"><span class="sd-mb-fill progress-bar-fill" '
        'data-width="{}" style="width:0;background:{}"></span></span>'
        '<span class="sd-mb-val">{}</span></div>',
        pct, color, value_str,
    )


def dashboard_callback(request, context):
    t = s.today()
    cur_start = s.rolling_start()               # последние 30 дней (t-29 … t)
    prev_start = cur_start - timedelta(days=30)  # предыдущие 30 дней (t-59 … t-30)
    prev_end = cur_start - timedelta(days=1)

    cash = get_cash_balance()
    wh = s.warehouse_value()
    s_today = s.sales_today()
    s_yesterday = s.sales_yesterday()
    profit_30 = profit(cur_start, t)
    profit_prev = profit(prev_start, prev_end)
    debt = s.total_debt()
    _, debtors_count = s.top_debtors()
    low = s.low_stock_products()

    # KPI. Правило: у карточек с трендом ЧИСЛО нейтральное (sd-slate), цвет —
    # только у бейджа ▲/▼ (иначе при развороте тренда число и бейдж противоречат).
    # У карточек без тренда число красится в фирменный цвет категории.
    # Иконка ВСЕГДА в цвете категории (чистая категоризация, тренда не касается).
    kpis = [
        {"icon": "payments", "label": "Касса", "value": s.money(cash), "target": int(cash),
         "unit": "сом", "sub": "сейчас", "value_class": "sd-slate", "icon_color": "sd-icon-blue6",
         "href": "/admin/finance/cashflow/"},
        {"icon": "receipt_long", "label": "Продажи за сегодня", "value": s.money(s_today), "target": int(s_today),
         "unit": "сом", "sub": "за сегодня", "value_class": "sd-slate", "icon_color": "sd-icon-indigo",
         "href": "/admin/sales/sale/", "trend": _trend(s_today, s_yesterday)},
        {"icon": "trending_up", "label": "Прибыль за 30 дней", "value": s.money(profit_30), "target": int(profit_30),
         "unit": "сом", "sub": "за 30 дней", "value_class": "sd-slate", "icon_color": "sd-icon-emerald",
         "href": "/admin/finance/cashflow/", "trend": _trend(profit_30, profit_prev)},
        {"icon": "inventory_2", "label": "Стоимость склада", "value": s.money(wh["value"]), "target": int(wh["value"]),
         "unit": "сом", "sub": f"{fmt_qty(wh['units'])} ед. на складе", "value_class": "sd-slate",
         "icon_color": "sd-icon-sky6", "href": "/admin/catalog/product/"},
        {"icon": "groups", "label": "Долги клиентов", "value": s.money(debt), "target": int(debt),
         "unit": "сом", "sub": f"{debtors_count} должников", "value_class": "sd-slate",
         "icon_color": "sd-icon-amber6", "href": "/admin/debts/debt/"},
        {"icon": "warning", "label": "На пополнение", "value": str(len(low)), "target": len(low),
         "unit": "товаров", "sub": "ниже порога", "value_class": "sd-red",
         "icon_color": "sd-icon-red", "href": "/admin/catalog/product/"},
    ]
    for k in kpis:
        # Единое правило без исключений: число всегда нейтральное (sd-slate).
        # Категория живёт только в иконке, сигнал «хорошо/плохо» — только в тренд-бейдже.
        k["value_class"] = "sd-slate"
        k["icon_class"] = f"{k['icon_color']} sd-icon-shift"

    # --- данные графиков (float только тут, на выходе в JSON) ---
    rev = s.revenue_by_day(30)
    revenue_data = {"labels": [r["label"] for r in rev], "values": [r["value"] for r in rev]}

    max_rev = max((r["value"] for r in rev), default=0) or 1
    tracker = []
    for r in rev:
        ratio = r["value"] / max_rev
        level = 0 if r["value"] <= 0 else (1 if ratio < 0.25 else (2 if ratio < 0.5 else (3 if ratio < 0.75 else 4)))
        tracker.append({"color": f"sd-track-{level}", "tooltip": f"{r['label']}: {s.money(r['value'])} сом"})

    pay = s.payment_split()
    payment_data = {"cash": float(pay["cash"]), "debt": float(pay["debt"])}

    # --- ТОП-5 товаров (нейтральный бар — это рейтинг) ---
    top = s.top_products(limit=5)
    max_top = max((r["revenue"] for r in top), default=0) or 1
    top_rows = []
    for r in top:
        pct = round(float(r["revenue"] / max_top * 100))
        name_cell = format_html(
            '<a href="/admin/catalog/product/{}/change/" class="sd-link">{}</a>', r["id"], r["name"])
        top_rows.append([name_cell, f"{fmt_qty(r['qty'])} шт", _minibar(s.money(r["revenue"]), pct, "#94a3b8")])
    top_table = {"headers": ["Товар", "Продано", "Выручка"], "rows": top_rows}
    top_title = mark_safe(
        '<span class="material-symbols-outlined sd-titleicon" style="color:#f59e0b">'
        'workspace_premium</span>ТОП-5 товаров за 30 дней')

    context.update({
        "dash_kpis": kpis,
        "dash_revenue_data": json.dumps(revenue_data, ensure_ascii=False),
        "dash_tracker": tracker,
        "dash_payment_data": json.dumps(payment_data, ensure_ascii=False),
        "dash_payment_cash": s.money(pay["cash"]),
        "dash_payment_debt": s.money(pay["debt"]),
        "dash_payment_has_data": (pay["cash"] + pay["debt"]) > 0,
        "dash_top_table": top_table,
        "dash_top_title": top_title,
        "dash_top_has_data": bool(top),
    })
    return context
