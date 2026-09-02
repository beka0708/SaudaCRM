"""Расчёт метрик для дашборда.

Все функции возвращают простые данные (числа, списки dict) — их собирает
analytics.dashboard.dashboard_callback. Логика опирается на уже готовые модели:
продажи, склад-движения, касса, долги.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, F, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

DEC = DecimalField(max_digits=20, decimal_places=2)
ZERO = Decimal("0")


# ---------- утилиты дат / форматирования ----------

def today():
    return timezone.localdate()


def month_start(d=None):
    d = d or today()
    return d.replace(day=1)


def prev_month_range(d=None):
    d = d or today()
    first = d.replace(day=1)
    last_prev = first - timedelta(days=1)
    return last_prev.replace(day=1), last_prev


def money(value) -> str:
    """1240000 -> '1 240 000'."""
    value = value or ZERO
    return f"{value:,.0f}".replace(",", " ")


def _pct_change(current, previous):
    """Процент изменения current относительно previous (или None)."""
    current = current or ZERO
    previous = previous or ZERO
    if previous == 0:
        return None
    return float((current - previous) / previous * 100)


# ---------- склад ----------

def _products_with_stock():
    from apps.catalog.models import Product

    # annotate называем stock_qty, т.к. у Product уже есть property .stock (без сеттера).
    return Product.objects.annotate(
        stock_qty=Coalesce(Sum("movements__quantity"), ZERO, output_field=DEC)
    )


def warehouse_value():
    """Стоимость склада по себестоимости + количество единиц."""
    value, units = ZERO, ZERO
    for p in _products_with_stock():
        value += p.stock_qty * p.cost_price
        units += p.stock_qty
    return {"value": value, "units": units}


def low_stock_products():
    """Товары ниже порога пополнения (с разбивкой по фасовке)."""
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

def sales_total(start=None, end=None):
    from apps.sales.models import Sale

    qs = Sale.objects.all()
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    return qs.aggregate(s=Sum("total"))["s"] or ZERO


def sales_today():
    return sales_total(today(), today())


def sales_yesterday():
    y = today() - timedelta(days=1)
    return sales_total(y, y)


def revenue_by_day(days=30):
    """Выручка по дням за последние `days` дней (с заполнением пропусков нулями)."""
    from apps.sales.models import Sale

    start = today() - timedelta(days=days - 1)
    raw = (
        Sale.objects.filter(created_at__date__gte=start)
        .annotate(d=TruncDate("created_at"))
        .values("d")
        .annotate(total=Sum("total"))
    )
    by_day = {r["d"]: r["total"] or ZERO for r in raw}
    labels, values = [], []
    for i in range(days):
        d = start + timedelta(days=i)
        labels.append(d.strftime("%d.%m"))
        values.append(float(by_day.get(d, ZERO)))
    return {"labels": labels, "values": values}


def payment_split(start=None):
    """Сумма продаж по типам оплаты за период (по умолчанию — текущий месяц)."""
    from apps.sales.models import Sale

    start = start or month_start()
    rows = (
        Sale.objects.filter(created_at__date__gte=start)
        .values("payment_type")
        .annotate(total=Sum("total"))
    )
    result = {"cash": ZERO, "debt": ZERO}
    for r in rows:
        result[r["payment_type"]] = r["total"] or ZERO
    return result


def top_products(start=None, limit=8):
    """ТОП товаров по выручке за период (по умолчанию — текущий месяц)."""
    from apps.sales.models import SaleItem

    start = start or month_start()
    rows = (
        SaleItem.objects.filter(sale__created_at__date__gte=start)
        .values("product__name")
        .annotate(
            revenue=Sum(F("base_quantity") * F("price"), output_field=DEC),
            qty=Sum("base_quantity"),
        )
        .order_by("-revenue")[:limit]
    )
    return [
        {"name": r["product__name"], "revenue": r["revenue"] or ZERO, "qty": r["qty"] or ZERO}
        for r in rows
    ]


def margin_by_product(start=None, limit=8):
    """Маржинальность по товарам за период: прибыль и % (price − себестоимость)."""
    from apps.sales.models import SaleItem

    start = start or month_start()
    rows = (
        SaleItem.objects.filter(sale__created_at__date__gte=start)
        .values("product__name")
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
        result.append({"name": r["product__name"], "profit": profit, "pct": pct})
    return result


def stock_forecast(days=30, limit=6):
    """Прогноз запаса: на сколько дней хватит (остаток / средняя скорость продаж).

    Берём товары, которые продавались за период и ещё есть на складе; показываем
    те, что закончатся раньше всех.
    """
    from apps.sales.models import SaleItem

    start = today() - timedelta(days=days - 1)
    sold = {
        r["product_id"]: (r["qty"] or ZERO)
        for r in SaleItem.objects.filter(sale__created_at__date__gte=start)
        .values("product_id")
        .annotate(qty=Sum("base_quantity"))
    }
    result = []
    for p in _products_with_stock():
        qty_sold = sold.get(p.id, ZERO)
        if qty_sold <= 0 or p.stock_qty <= 0:
            continue
        avg_per_day = qty_sold / days
        days_left = int(p.stock_qty / avg_per_day) if avg_per_day else None
        result.append({"name": p.name, "days_left": days_left, "stock": p.stock_qty})
    result.sort(key=lambda x: x["days_left"] if x["days_left"] is not None else 10**9)
    return result[:limit]


# ---------- долги ----------

def total_debt():
    """Общая сумма долгов к получению = Σ долгов − Σ оплат."""
    from apps.debts.models import Debt, DebtPayment

    debts = Debt.objects.aggregate(s=Sum("amount"))["s"] or ZERO
    paid = DebtPayment.objects.aggregate(s=Sum("amount"))["s"] or ZERO
    return debts - paid


def top_debtors(limit=6):
    from apps.clients.models import Client

    rows = []
    for c in Client.objects.all():
        debt = c.current_debt
        if debt > 0:
            rows.append({"name": c.name, "debt": debt})
    rows.sort(key=lambda x: x["debt"], reverse=True)
    return rows[:limit], len(rows)
