"""Сборка данных дашборда для Unfold (DASHBOARD_CALLBACK).

Тонкий слой: берёт цифры из analytics.metrics и кладёт в контекст шаблона
templates/admin/index.html. Графики отдаём как JSON в формате Chart.js.
"""
import json

from apps.catalog.services import fmt_qty
from apps.finance.services import get_cash_balance, profit

from . import metrics as m


def _trend(current, previous):
    pct = m._pct_change(current, previous)
    if pct is None:
        return None
    return {"up": pct >= 0, "pct": abs(round(pct))}


def dashboard_callback(request, context):
    t = m.today()
    ms = m.month_start()
    pm_start, pm_end = m.prev_month_range()

    # --- цифры ---
    cash = get_cash_balance()
    wh = m.warehouse_value()
    s_today = m.sales_today()
    s_yesterday = m.sales_yesterday()
    profit_month = profit(ms, t)
    profit_prev = profit(pm_start, pm_end)
    debt = m.total_debt()
    debtors, debtors_count = m.top_debtors()
    low = m.low_stock_products()

    kpis = [
        {
            "icon": "💰",
            "label": "Касса",
            "value": m.money(cash),
            "sub": "сом сейчас",
            "accent": "green",
        },
        {
            "icon": "🧾",
            "label": "Продажи за сегодня",
            "value": m.money(s_today),
            "sub": "сом",
            "accent": "green",
            "trend": _trend(s_today, s_yesterday),
        },
        {
            "icon": "📈",
            "label": "Прибыль за месяц",
            "value": m.money(profit_month),
            "sub": "приход − расход",
            "accent": "green" if profit_month >= 0 else "red",
            "trend": _trend(profit_month, profit_prev),
        },
        {
            "icon": "📦",
            "label": "Стоимость склада",
            "value": m.money(wh["value"]),
            "sub": f"{fmt_qty(wh['units'])} ед. на складе",
            "accent": "blue",
        },
        {
            "icon": "🧍",
            "label": "Долги клиентов",
            "value": m.money(debt),
            "sub": f"{debtors_count} должников",
            "accent": "amber",
        },
        {
            "icon": "⚠️",
            "label": "На пополнение",
            "value": str(len(low)),
            "sub": "товаров ниже порога",
            "accent": "red" if low else "green",
        },
    ]

    # --- графики (Chart.js) ---
    rev = m.revenue_by_day(30)
    revenue_chart = {
        "labels": rev["labels"],
        "datasets": [
            {
                "label": "Выручка",
                "data": rev["values"],
                "backgroundColor": "#10b981",
                "borderColor": "#10b981",
                "borderRadius": 4,
            }
        ],
    }

    pay = m.payment_split()
    payment_chart = {
        "labels": ["Наличные", "Реализация"],
        "datasets": [
            {
                "data": [float(pay["cash"]), float(pay["debt"])],
                "backgroundColor": ["#10b981", "#f59e0b"],
                "borderWidth": 0,
            }
        ],
    }

    # --- таблицы ---
    top = [
        {"name": r["name"], "revenue": m.money(r["revenue"]), "qty": fmt_qty(r["qty"])}
        for r in m.top_products()
    ]
    margin = [
        {"name": r["name"], "profit": m.money(r["profit"]), "pct": round(r["pct"])}
        for r in m.margin_by_product()
    ]
    debtor_rows = [{"name": r["name"], "debt": m.money(r["debt"])} for r in debtors]
    forecast = [
        {"name": r["name"], "days_left": r["days_left"], "stock": fmt_qty(r["stock"])}
        for r in m.stock_forecast()
    ]

    context.update(
        {
            "dash_kpis": kpis,
            "dash_revenue_json": json.dumps(revenue_chart, ensure_ascii=False),
            "dash_payment_json": json.dumps(payment_chart, ensure_ascii=False),
            "dash_payment_has_data": (pay["cash"] + pay["debt"]) > 0,
            "dash_top_products": top,
            "dash_margin": margin,
            "dash_low_stock": low,
            "dash_debtors": debtor_rows,
            "dash_forecast": forecast,
        }
    )
    return context
