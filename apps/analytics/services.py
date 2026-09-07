"""Аналитика: единый слой расчётов для дашборда и страницы «Аналитика».

Вся арифметика — здесь. dashboard_callback и analytics-view только собирают
контекст из этих функций (никаких вычислений в шаблонах/вьюхах).
Опирается на готовые модели: продажи, склад-движения, касса, долги.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import DecimalField, F, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

DEC = DecimalField(max_digits=20, decimal_places=2)
ZERO = Decimal("0")


# ---------- даты / форматирование ----------

def today():
    return timezone.localdate()


def month_start(d=None):
    return (d or today()).replace(day=1)


def rolling_start(days=30):
    """Начало скользящего окна (по умолчанию последние 30 дней, включая сегодня)."""
    return today() - timedelta(days=days - 1)


def prev_month_range(d=None):
    d = d or today()
    first = d.replace(day=1)
    last_prev = first - timedelta(days=1)
    return last_prev.replace(day=1), last_prev


def money(value) -> str:
    """1240000 -> '1 240 000' (Decimal форматируется напрямую, без float)."""
    return f"{value or ZERO:,.0f}".replace(",", " ")


def pct_change(current, previous):
    current = current or ZERO
    previous = previous or ZERO
    if previous == 0:
        return None
    return float((current - previous) / previous * 100)


# ---------- склад ----------

def _products_with_stock():
    from apps.catalog.models import Product

    # annotate называем stock_qty: у Product есть property .stock (без сеттера).
    return Product.objects.annotate(
        stock_qty=Coalesce(Sum("movements__quantity"), ZERO, output_field=DEC)
    )


def warehouse_value():
    value, units = ZERO, ZERO
    for p in _products_with_stock():
        value += p.stock_qty * p.cost_price
        units += p.stock_qty
    return {"value": value, "units": units}


def low_stock_products():
    from apps.catalog.services import fmt_qty, stock_breakdown

    rows = []
    qs = _products_with_stock().filter(
        low_stock_threshold__gt=0, stock_qty__lt=F("low_stock_threshold")
    ).order_by("stock_qty")
    for p in qs:
        rows.append(
            {
                "name": p.name,
                "stock_label": stock_breakdown(p, p.stock_qty),
                "threshold": f"{fmt_qty(p.low_stock_threshold)} {p.base_unit}",
            }
        )
    return rows


# ---------- продажи ----------

def _sales_qs(start=None, end=None):
    from apps.sales.models import Sale

    qs = Sale.objects.all()
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    return qs


def sales_total(start=None, end=None):
    return _sales_qs(start, end).aggregate(s=Sum("total"))["s"] or ZERO


def sales_count(start=None, end=None):
    return _sales_qs(start, end).count()


def avg_check(start=None, end=None):
    total = sales_total(start, end)
    cnt = sales_count(start, end)
    return (total / cnt) if cnt else ZERO


def sales_today():
    return sales_total(today(), today())


def sales_yesterday():
    y = today() - timedelta(days=1)
    return sales_total(y, y)


def revenue_by_day(days=30):
    """Выручка по дням за последние `days` дней (пропуски заполнены нулями)."""
    from apps.sales.models import Sale

    start = today() - timedelta(days=days - 1)
    raw = (
        Sale.objects.filter(created_at__date__gte=start)
        .annotate(d=TruncDate("created_at"))
        .values("d")
        .annotate(total=Sum("total"))
    )
    by_day = {r["d"]: r["total"] or ZERO for r in raw}
    out = []
    for i in range(days):
        d = start + timedelta(days=i)
        out.append({"date": d, "label": d.strftime("%d.%m"), "value": float(by_day.get(d, ZERO))})
    return out


def payment_split(start=None):
    """Сумма продаж по типам оплаты за период (по умолчанию — текущий месяц)."""
    from apps.sales.models import Sale

    start = start or rolling_start()
    rows = (
        Sale.objects.filter(created_at__date__gte=start)
        .values("payment_type")
        .annotate(total=Sum("total"))
    )
    result = {"cash": ZERO, "debt": ZERO}
    for r in rows:
        result[r["payment_type"]] = r["total"] or ZERO
    return result


def _saleitems_qs(start=None, end=None):
    from apps.sales.models import SaleItem

    qs = SaleItem.objects.all()
    if start:
        qs = qs.filter(sale__created_at__date__gte=start)
    if end:
        qs = qs.filter(sale__created_at__date__lte=end)
    return qs


def top_products(start=None, end=None, limit=8):
    start = start or rolling_start()
    rows = (
        _saleitems_qs(start, end)
        .values("product", "product__name")
        .annotate(
            revenue=Sum(F("base_quantity") * F("price"), output_field=DEC),
            qty=Sum("base_quantity"),
        )
        .order_by("-revenue")[:limit]
    )
    return [
        {"id": r["product"], "name": r["product__name"],
         "revenue": r["revenue"] or ZERO, "qty": r["qty"] or ZERO}
        for r in rows
    ]


def margin_by_product(start=None, end=None, limit=12):
    start = start or rolling_start()
    rows = (
        _saleitems_qs(start, end)
        .values("product", "product__name")
        .annotate(
            revenue=Sum(F("base_quantity") * F("price"), output_field=DEC),
            profit=Sum(
                F("base_quantity") * (F("price") - F("product__cost_price")),
                output_field=DEC,
            ),
        )
        .order_by("-profit")[:limit]
    )
    result = []
    for r in rows:
        revenue = r["revenue"] or ZERO
        profit = r["profit"] or ZERO
        pct = float(profit / revenue * 100) if revenue else 0.0
        result.append({"id": r["product"], "name": r["product__name"], "profit": profit, "pct": pct})
    return result


def slow_movers(start=None, end=None, limit=8):
    """Медленно продаваемые: товары с наименьшими продажами за период (с остатком)."""
    start = start or rolling_start()
    sold = {
        r["product_id"]: (r["qty"] or ZERO)
        for r in _saleitems_qs(start, end).values("product_id").annotate(qty=Sum("base_quantity"))
    }
    rows = []
    for p in _products_with_stock():
        if p.stock_qty <= 0:
            continue
        rows.append({"id": p.id, "name": p.name, "qty_sold": sold.get(p.id, ZERO), "stock": p.stock_qty})
    rows.sort(key=lambda x: x["qty_sold"])
    return rows[:limit]


def stock_forecast(start=None, end=None, limit=12):
    """Прогноз запаса: на сколько дней хватит (остаток / средняя скорость продаж)."""
    start = start or rolling_start()
    end = end or today()
    days = max((end - start).days + 1, 1)
    sold = {
        r["product_id"]: (r["qty"] or ZERO)
        for r in _saleitems_qs(start, end).values("product_id").annotate(qty=Sum("base_quantity"))
    }
    result = []
    for p in _products_with_stock():
        qty_sold = sold.get(p.id, ZERO)
        if qty_sold <= 0 or p.stock_qty <= 0:
            continue
        avg_per_day = qty_sold / days
        days_left = int(p.stock_qty / avg_per_day) if avg_per_day else None
        result.append({"id": p.id, "name": p.name, "days_left": days_left, "stock": p.stock_qty})
    result.sort(key=lambda x: x["days_left"] if x["days_left"] is not None else 10**9)
    return result[:limit]


def period_summary(start, end):
    from apps.finance.services import profit

    return {
        "sales": sales_total(start, end),
        "profit": profit(start, end),
        "count": sales_count(start, end),
        "avg_check": avg_check(start, end),
    }


def month_comparison():
    """Текущий месяц vs предыдущий: продажи, прибыль, средний чек, число продаж."""
    ms = month_start()
    pm_start, pm_end = prev_month_range()
    return {"current": period_summary(ms, today()), "previous": period_summary(pm_start, pm_end)}


# ---------- долги ----------

def total_debt():
    from apps.debts.models import Debt, DebtPayment

    debts = Debt.objects.aggregate(s=Sum("amount"))["s"] or ZERO
    paid = DebtPayment.objects.aggregate(s=Sum("amount"))["s"] or ZERO
    return debts - paid


def top_debtors(limit=8):
    from apps.clients.models import Client

    rows = []
    for c in Client.objects.all():
        debt = c.current_debt
        if debt > 0:
            rows.append({"id": c.id, "name": c.name, "debt": debt})
    rows.sort(key=lambda x: x["debt"], reverse=True)
    return rows[:limit], len(rows)


def top_clients_by_purchase(start=None, end=None, limit=8):
    """ТОП клиентов по объёму закупок за период (сумма продаж клиенту)."""
    from apps.sales.models import Sale

    start = start or rolling_start()
    qs = Sale.objects.filter(created_at__date__gte=start, client__isnull=False)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    rows = (
        qs.values("client", "client__name")
        .annotate(total=Sum("total"))
        .order_by("-total")[:limit]
    )
    return [
        {"id": r["client"], "name": r["client__name"], "total": r["total"] or ZERO}
        for r in rows
    ]
