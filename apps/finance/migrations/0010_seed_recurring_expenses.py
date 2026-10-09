"""Постоянные расходы заказчика: суммы с его слов (октябрь 2026).

Заводим сразу, чтобы не настраивать руками после обновления. Суммы потом
правятся в админке — шаблон не документ. Повторный прогон ничего не
задваивает: создаём только то, чего ещё нет по названию.
"""
from django.db import migrations

SEED = [
    ("Бух услуги", "other_out", "20000"),
    ("Страховка", "other_out", "1730"),
    ("ЗП Кайнар", "salary", "70000"),
]


def seed(apps, schema_editor):
    RecurringExpense = apps.get_model("finance", "RecurringExpense")
    for name, category, amount in SEED:
        RecurringExpense.objects.get_or_create(
            name=name,
            defaults={"category": category, "amount": amount, "day": None},
        )


def unseed(apps, schema_editor):
    RecurringExpense = apps.get_model("finance", "RecurringExpense")
    # Удаляем только нетронутые шаблоны: если по нему уже проводили расход,
    # оставляем — иначе у CashFlow оборвётся ссылка на источник.
    RecurringExpense.objects.filter(
        name__in=[n for n, _, _ in SEED], postings__isnull=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0009_recurringexpense_cashflow_recurring"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
