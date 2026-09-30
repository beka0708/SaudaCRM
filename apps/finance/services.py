"""Бизнес-логика финансов: касса, приходы/расходы, прибыль.

Единая точка изменения денег. Вызывают админка, бот, sales (наличная продажа)
и debts (оплата долга). Все суммы — Decimal, 2 знака.
"""
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from .models import CashFlow


# Группировка категорий (единый источник для админки и бота).
EXPENSE_CATEGORIES = [
    CashFlow.Category.PURCHASE,
    CashFlow.Category.DELIVERY,
    CashFlow.Category.RENT,
    CashFlow.Category.SALARY,
    CashFlow.Category.PERSONAL,
    CashFlow.Category.OTHER_OUT,
]
INCOME_CATEGORIES = [
    CashFlow.Category.SALE,
    CashFlow.Category.DEBT_PAYMENT,
    CashFlow.Category.INVESTMENT,
    CashFlow.Category.OTHER_IN,
]

# --- Статьи расходов (список заказчика) ---------------------------------
# Это то, что человек выбирает кнопкой в боте. Каждая статья ложится на
# укрупнённую Category: по ней считаются касса и прибыль, а сама статья
# пишется в CashFlow.subcategory — по ней потом можно фильтровать.
#
# ВАЖНО: личные расходы Атая укрупнённо всегда PERSONAL. Они уменьшают
# кассу, но НЕ входят в расходы бизнеса и не уменьшают прибыль
# (см. analytics.services.operating_expenses).

COMPANY_EXPENSE_ITEMS = [
    ("Сушняк", CashFlow.Category.OTHER_OUT),
    ("Топливо", CashFlow.Category.DELIVERY),
    ("Питание", CashFlow.Category.OTHER_OUT),
    ("ЗП Грузчикам", CashFlow.Category.SALARY),
    ("Стоянка", CashFlow.Category.DELIVERY),
    ("Амморт", CashFlow.Category.DELIVERY),
    ("Домой", CashFlow.Category.OTHER_OUT),
    ("ЗП Исмаила", CashFlow.Category.SALARY),
]

PERSONAL_EXPENSE_ITEMS = [
    ("Питание", CashFlow.Category.PERSONAL),
    ("Топливо", CashFlow.Category.PERSONAL),
    ("Благотвор", CashFlow.Category.PERSONAL),
    ("Авто", CashFlow.Category.PERSONAL),
    ("Шоппинг", CashFlow.Category.PERSONAL),
    ("Развлечение", CashFlow.Category.PERSONAL),
    ("Здоровье", CashFlow.Category.PERSONAL),
    ("Домой", CashFlow.Category.PERSONAL),
    ("Такси", CashFlow.Category.PERSONAL),
    ("Мойка", CashFlow.Category.PERSONAL),
    ("Сушняк", CashFlow.Category.PERSONAL),
]


def expense_category_for(item_name, personal=False):
    """Укрупнённая категория для статьи расхода. Незнакомая → «прочее»."""
    items = PERSONAL_EXPENSE_ITEMS if personal else COMPANY_EXPENSE_ITEMS
    for name, cat in items:
        if name == item_name:
            return cat
    return CashFlow.Category.PERSONAL if personal else CashFlow.Category.OTHER_OUT


def _dec(value) -> Decimal:
    return Decimal(str(value))


def record_cash_flow(
    direction, category, amount, date=None, comment="", sale=None, debt_payment=None,
    subcategory="",
):
    """Записать движение денег. Нулевые/отрицательные суммы игнорируем."""
    amount = _dec(amount)
    if amount <= 0:
        return None
    return CashFlow.objects.create(
        direction=direction,
        category=category,
        amount=amount,
        date=date or timezone.localdate(),
        comment=comment,
        subcategory=subcategory,
        sale=sale,
        debt_payment=debt_payment,
    )


def get_cash_balance() -> Decimal:
    """Текущий остаток кассы = сумма приходов − сумма расходов."""
    agg = CashFlow.objects.aggregate(
        inc=Sum("amount", filter=Q(direction=CashFlow.Direction.IN)),
        exp=Sum("amount", filter=Q(direction=CashFlow.Direction.OUT)),
    )
    return (agg["inc"] or Decimal("0")) - (agg["exp"] or Decimal("0"))


def _period_qs(start=None, end=None):
    qs = CashFlow.objects.all()
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    return qs


def total_income(start=None, end=None) -> Decimal:
    s = _period_qs(start, end).filter(direction=CashFlow.Direction.IN).aggregate(
        s=Sum("amount")
    )["s"]
    return s or Decimal("0")


def total_expense(start=None, end=None) -> Decimal:
    s = _period_qs(start, end).filter(direction=CashFlow.Direction.OUT).aggregate(
        s=Sum("amount")
    )["s"]
    return s or Decimal("0")


def profit(start=None, end=None) -> Decimal:
    """Прибыль за период = приходы − расходы (кассовый метод, как в ТЗ 3.7)."""
    return total_income(start, end) - total_expense(start, end)


# --- Авто-проводки из других разделов ---

def record_sale_income(sale):
    """Наличная продажа → приход денег в кассу (датой продажи)."""
    return record_cash_flow(
        CashFlow.Direction.IN,
        CashFlow.Category.SALE,
        sale.total,
        date=timezone.localdate(sale.created_at),
        comment=f"Продажа #{sale.pk}",
        sale=sale,
    )


def record_debt_payment_income(payment):
    """Оплата долга (реализация) → приход денег в кассу (датой оплаты)."""
    return record_cash_flow(
        CashFlow.Direction.IN,
        CashFlow.Category.DEBT_PAYMENT,
        payment.amount,
        date=timezone.localdate(payment.created_at),
        comment=f"Оплата долга #{payment.debt_id}",
        debt_payment=payment,
    )


def add_expense(category, amount, date=None, comment="", subcategory=""):
    """Удобная запись расхода."""
    return record_cash_flow(
        CashFlow.Direction.OUT, category, amount,
        date=date, comment=comment, subcategory=subcategory,
    )
