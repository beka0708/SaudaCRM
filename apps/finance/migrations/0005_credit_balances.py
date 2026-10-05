"""Актуальные остатки по кредитам (цифры заказчика на 05.10.2026).

    Кредит 1,7 млн — осталось 600 000
    Кредит 1,3 млн — осталось 500 000

Заводим не напрямую в `opening_amount`, а через остаток: если по кредиту
уже проходили платежи, простая запись в начальную сумму сдвинула бы
остаток на сумму этих платежей. Поэтому считаем
`opening_amount = нужный остаток + уже оплачено` — тогда остаток
получится ровно тем, который назвал заказчик, независимо от истории.
"""
from decimal import Decimal

from django.db import migrations
from django.db.models import Sum

TARGET_REMAINING = {
    "credit_17": Decimal("600000"),
    "credit_13": Decimal("500000"),
}


def set_balances(apps, schema_editor):
    Obligation = apps.get_model("finance", "Obligation")
    for code, target in TARGET_REMAINING.items():
        o = Obligation.objects.filter(code=code).first()
        if not o:
            continue
        paid = o.payments.filter(is_reversed=False).aggregate(
            s=Sum("amount"))["s"] or Decimal("0")
        o.opening_amount = target + paid
        o.save(update_fields=["opening_amount"])


def noop(apps, schema_editor):
    """Откат: прежние суммы были предварительными, возвращать нечего."""


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0004_seed_obligations"),
    ]

    operations = [migrations.RunPython(set_balances, noop)]
