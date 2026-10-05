"""Завести наши долги: два кредита и долг Ашимжану.

Цифры по Ашимжану — с его слов на 05.10.2026: остаток 71 493 $ по
фиксированному курсу 87,8 (= 6 277 085 сом). Курс заказчик просил
держать постоянным, поэтому он записан в самом обязательстве.

Остатки по кредитам — последние известные (из его таблицы на 29.09).
Точные суммы он пришлёт отдельно; поправить их можно прямо в админке,
пересчёт остатка произойдёт сам.
"""
from decimal import Decimal

from django.db import migrations


def seed(apps, schema_editor):
    Obligation = apps.get_model("finance", "Obligation")
    for data in (
        {
            "code": "credit_17", "name": "Кредит 1,7 млн",
            "currency": "KGS", "rate": Decimal("1"),
            "opening_amount": Decimal("1050000"),
            "default_payment": Decimal("50000"),
        },
        {
            "code": "credit_13", "name": "Кредит 1,3 млн",
            "currency": "KGS", "rate": Decimal("1"),
            "opening_amount": Decimal("860000"),
            "default_payment": Decimal("40000"),
        },
        {
            "code": "ashimzhan", "name": "Долг Ашимжану",
            "currency": "USD", "rate": Decimal("87.80"),
            "opening_amount": Decimal("71493"),
            "default_payment": None,   # сумму вводят вручную
        },
    ):
        Obligation.objects.get_or_create(code=data["code"], defaults=data)


def unseed(apps, schema_editor):
    Obligation = apps.get_model("finance", "Obligation")
    Obligation.objects.filter(
        code__in=["credit_17", "credit_13", "ashimzhan"], payments__isnull=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0003_obligation_alter_cashflow_category_obligationpayment"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
