"""Аналитика: единый слой расчётов для дашборда и страницы «Аналитика».

Вся арифметика — здесь. dashboard_callback и analytics-view только собирают
контекст из этих функций (никаких вычислений в шаблонах/вьюхах).
Опирается на готовые модели: продажи, склад-движения, касса, долги.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import DecimalField, F, OuterRef, Subquery, Sum, Value
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


def money(value, dec=0) -> str:
    """1240000 -> '1 240 000' (Decimal форматируется напрямую, без float).

    `dec` — знаков после запятой (в утреннем дайджесте выручка идёт с копейками).
    Принимает и строку: в состоянии бота суммы лежат текстом.
    """
    if not isinstance(value, Decimal):
        value = Decimal(str(value or 0))
    return f"{value:,.{dec}f}".replace(",", " ")


def pct_change(current, previous):
    current = current or ZERO
    previous = previous or ZERO
    if previous == 0:
        return None
    return float((current - previous) / previous * 100)


# ---------- склад ----------

def _products_with_stock():
    from apps.catalog.models import Product

    # stock_qty — остаток В ФАСОВКАХ (сумма остатков партий). Не .stock (property).
    return Product.objects.annotate(
        stock_qty=Coalesce(Sum("batches__packs_remaining"), 0)
    )


def warehouse_value():
    """Стоимость склада (по себестоимости партий) + остаток в фасовках."""
    from apps.warehouse.models import Batch

    agg = Batch.objects.aggregate(
        value=Coalesce(
            Sum(F("packs_remaining") * F("product__units_per_pack") * F("cost_per_unit"),
                output_field=DEC),
            Value(0, output_field=DEC),
        ),
        packs=Coalesce(Sum("packs_remaining"), 0),
    )
    return {"value": agg["value"] or ZERO, "units": agg["packs"] or 0}


def low_stock_products():
    from apps.catalog.services import pack_label, stock_breakdown

    rows = []
    qs = _products_with_stock().filter(
        low_stock_threshold__gt=0, stock_qty__lt=F("low_stock_threshold")
    ).order_by("stock_qty")
    for p in qs:
        rows.append(
            {
                "name": p.name,
                "stock_label": stock_breakdown(p, p.stock_qty),
                "threshold": (
                    f"{p.low_stock_threshold} "
                    f"{pack_label(p.pack_name, p.low_stock_threshold)}"
                ),
            }
        )
    return rows


# ---------- продажи ----------

def _sales_qs(start=None, end=None):
    from apps.sales.models import Sale

    # .active() — без сторнированных: отменённая продажа не должна попадать
    # ни в выручку, ни в прибыль, ни в ТОПы.
    qs = Sale.objects.active()
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
        Sale.objects.active()
        .filter(created_at__date__gte=start)
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
        Sale.objects.active()
        .filter(created_at__date__gte=start)
        .values("payment_type")
        .annotate(total=Sum("total"))
    )
    result = {"cash": ZERO, "debt": ZERO}
    for r in rows:
        result[r["payment_type"]] = r["total"] or ZERO
    return result


def _saleitems_qs(start=None, end=None):
    from apps.sales.models import SaleItem

    # Позиции сторнированных продаж исключаем — товар вернулся в партии.
    qs = SaleItem.objects.filter(sale__is_reversed=False)
    if start:
        qs = qs.filter(sale__created_at__date__gte=start)
    if end:
        qs = qs.filter(sale__created_at__date__lte=end)
    return qs


def top_products(start=None, end=None, limit=8):
    start = start or rolling_start()
    rev_expr = F("packs") * F("product__units_per_pack") * F("price_per_unit")
    rows = (
        _saleitems_qs(start, end)
        .values("product", "product__name")
        .annotate(
            revenue=Sum(rev_expr, output_field=DEC),
            qty=Sum("packs"),
        )
        .order_by("-revenue")[:limit]
    )
    return [
        {"id": r["product"], "name": r["product__name"],
         "revenue": r["revenue"] or ZERO, "qty": r["qty"] or 0}
        for r in rows
    ]


def margin_by_product(start=None, end=None, limit=12):
    start = start or rolling_start()
    rev_expr = F("packs") * F("product__units_per_pack") * F("price_per_unit")
    rows = (
        _saleitems_qs(start, end)
        .values("product", "product__name")
        .annotate(
            revenue=Sum(rev_expr, output_field=DEC),
            cost=Coalesce(Sum("cogs"), Value(0, output_field=DEC)),
        )
    )
    result = []
    for r in rows:
        revenue = r["revenue"] or ZERO
        profit = revenue - (r["cost"] or ZERO)  # реальная FIFO-себестоимость
        pct = float(profit / revenue * 100) if revenue else 0.0
        result.append({"id": r["product"], "name": r["product__name"], "profit": profit, "pct": pct})
    result.sort(key=lambda x: x["profit"], reverse=True)
    return result[:limit]


def slow_movers(start=None, end=None, limit=8):
    """Медленно продаваемые: товары с наименьшими продажами за период (с остатком)."""
    start = start or rolling_start()
    sold = {
        r["product_id"]: (r["packs"] or 0)
        for r in _saleitems_qs(start, end).values("product_id").annotate(packs=Sum("packs"))
    }
    rows = []
    for p in _products_with_stock():
        if p.stock_qty <= 0:
            continue
        rows.append({"id": p.id, "name": p.name, "qty_sold": sold.get(p.id, 0), "stock": p.stock_qty})
    rows.sort(key=lambda x: x["qty_sold"])
    return rows[:limit]


def stock_forecast(start=None, end=None, limit=12):
    """Прогноз запаса: на сколько дней хватит (остаток / средняя скорость продаж)."""
    start = start or rolling_start()
    end = end or today()
    days = max((end - start).days + 1, 1)
    sold = {
        r["product_id"]: (r["packs"] or 0)
        for r in _saleitems_qs(start, end).values("product_id").annotate(packs=Sum("packs"))
    }
    result = []
    for p in _products_with_stock():
        qty_sold = sold.get(p.id, 0)
        if qty_sold <= 0 or p.stock_qty <= 0:
            continue
        avg_per_day = qty_sold / days
        days_left = int(p.stock_qty / avg_per_day) if avg_per_day else None
        result.append({"id": p.id, "name": p.name, "days_left": days_left, "stock": p.stock_qty})
    result.sort(key=lambda x: x["days_left"] if x["days_left"] is not None else 10**9)
    return result[:limit]


# ---------- показатели «как в старом боте» (для утреннего дайджеста) ----------

def revenue_and_cogs(start, end):
    """Выручка и себестоимость ПРОДАННОГО за период (по позициям продаж)."""
    rev_expr = F("packs") * F("product__units_per_pack") * F("price_per_unit")
    agg = _saleitems_qs(start, end).aggregate(
        revenue=Coalesce(Sum(rev_expr, output_field=DEC), Value(0, output_field=DEC)),
        cogs=Coalesce(Sum("cogs"), Value(0, output_field=DEC)),
    )
    return {"revenue": agg["revenue"] or ZERO, "cogs": agg["cogs"] or ZERO}


def _expenses_qs(start, end):
    from apps.finance.models import CashFlow

    return CashFlow.objects.filter(
        direction=CashFlow.Direction.OUT, date__gte=start, date__lte=end
    )


def operating_expenses(start, end):
    """Расходы БИЗНЕСА за период: без закупки товара и без личных расходов.

    Закупка — не расход периода: стоимость товара попадает в отчёт через
    себестоимость проданного (COGS) в момент продажи. Если считать и закупку,
    и себестоимость, товар учтётся дважды и прибыль уедет в минус.

    Личные расходы владельца — не затраты бизнеса, а изъятие: они уменьшают
    кассу, но не прибыль. Поэтому и в дайджесте они идут отдельным блоком.

    Обе поправки сверены с их таблицей «Показатели»: сходится в ноль по всем
    месяцам 2026 года.
    """
    from apps.finance.models import CashFlow

    s = (
        _expenses_qs(start, end)
        .exclude(category__in=[CashFlow.Category.PURCHASE, CashFlow.Category.PERSONAL])
        .aggregate(s=Sum("amount"))["s"]
    )
    return s or ZERO


def expenses_by_category(category, start, end):
    """Сумма расходов одной категории за период (напр. личные расходы Атая)."""
    s = _expenses_qs(start, end).filter(category=category).aggregate(s=Sum("amount"))["s"]
    return s or ZERO


def month_indicators(start, end):
    """Показатели периода: выручка, себестоимость, расходы, ЧИСТАЯ ПРИБЫЛЬ.

    Прибыль = выручка − себестоимость − расходы (метод начисления), а НЕ
    `finance.services.profit` (кассовый: приход − расход). Обе метрики нужны:
    кассовая показывает движение денег, эта — заработок на товаре.
    """
    rc = revenue_and_cogs(start, end)
    expenses = operating_expenses(start, end)
    return {
        "revenue": rc["revenue"],
        "cogs": rc["cogs"],
        "expenses": expenses,
        "profit": rc["revenue"] - rc["cogs"] - expenses,
    }


def stock_report():
    """Остатки всех товаров: фасовки + стоимость по себестоимости. Один запрос."""
    from apps.catalog.services import pack_label
    from apps.warehouse.models import Batch

    rows = (
        Batch.objects.filter(packs_remaining__gt=0)
        .values("product__name", "product__pack_name")
        .annotate(
            packs=Sum("packs_remaining"),
            value=Coalesce(
                Sum(
                    F("packs_remaining") * F("product__units_per_pack") * F("cost_per_unit"),
                    output_field=DEC,
                ),
                Value(0, output_field=DEC),
            ),
        )
    )
    result = [
        {
            "name": r["product__name"],
            "packs": r["packs"] or 0,
            "pack_label": pack_label(r["product__pack_name"], r["packs"] or 0),
            "value": r["value"] or ZERO,
        }
        for r in rows
    ]
    # Сортируем в Python, а НЕ в БД: база создана с collation en_US.UTF-8, где
    # названия с пробелом («Масло растительное») уезжают в конец списка.
    # Так порядок не зависит от настроек сервера.
    result.sort(key=lambda r: r["name"].lower())
    return result, sum((r["value"] for r in result), ZERO)


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

    debts = Debt.objects.active().aggregate(s=Sum("amount"))["s"] or ZERO
    paid = (
        DebtPayment.objects.filter(is_reversed=False, debt__is_reversed=False)
        .aggregate(s=Sum("amount"))["s"]
        or ZERO
    )
    return debts - paid


def _debtors_qs():
    """Клиенты с ненулевым долгом, одним запросом (раньше был N+1 на дашборде).

    Отдельные подзапросы, чтобы JOIN не раздувал суммы. Сторно не считаем.
    """
    from apps.clients.models import Client
    from apps.debts.models import Debt, DebtPayment

    debt_amount = (
        Debt.objects.filter(client=OuterRef("pk"), is_reversed=False)
        .values("client").annotate(s=Sum("amount")).values("s")
    )
    paid = (
        DebtPayment.objects.filter(
            debt__client=OuterRef("pk"), is_reversed=False, debt__is_reversed=False
        )
        .values("debt__client").annotate(s=Sum("amount")).values("s")
    )
    return (
        Client.objects.annotate(
            debt_left=Coalesce(Subquery(debt_amount, output_field=DEC), Value(0, output_field=DEC))
            - Coalesce(Subquery(paid, output_field=DEC), Value(0, output_field=DEC))
        )
        .filter(debt_left__gt=0)
        .order_by("-debt_left")
    )


def top_debtors(limit=8):
    """ТОП должников для дашборда: строки + общее число должников."""
    qs = _debtors_qs()
    total = qs.count()
    rows = [{"id": c.id, "name": c.name, "debt": c.debt_left} for c in qs[:limit]]
    return rows, total


def all_debtors():
    """ВСЕ должники + итоговая сумма — для утреннего дайджеста (там без обрезки)."""
    rows = [
        {"id": c.id, "name": c.name, "debt": c.debt_left} for c in _debtors_qs()
    ]
    return rows, sum((r["debt"] for r in rows), ZERO)


def top_clients_by_profit(start=None, end=None, limit=8):
    """ТОП клиентов по ПРИБЫЛИ за период (ТЗ 10: «самые прибыльные клиенты»).

    Прибыль = выручка − реальная FIFO-себестоимость (`cogs`), а не оборот:
    крупный покупатель с большой скидкой может приносить меньше маленького.
    Наличные продажи без клиента в рейтинг не попадают.
    """
    start = start or rolling_start()
    rev_expr = F("packs") * F("product__units_per_pack") * F("price_per_unit")
    rows = (
        _saleitems_qs(start, end)
        .filter(sale__client__isnull=False)
        .values("sale__client", "sale__client__name")
        .annotate(
            revenue=Sum(rev_expr, output_field=DEC),
            cost=Coalesce(Sum("cogs"), Value(0, output_field=DEC)),
        )
    )
    result = []
    for r in rows:
        revenue = r["revenue"] or ZERO
        profit = revenue - (r["cost"] or ZERO)
        result.append({
            "id": r["sale__client"],
            "name": r["sale__client__name"],
            "profit": profit,
            "total": revenue,
            "pct": float(profit / revenue * 100) if revenue else 0.0,
        })
    result.sort(key=lambda x: x["profit"], reverse=True)
    return result[:limit]
