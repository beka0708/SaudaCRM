"""Быстрая сводка по деньгам: python manage.py cashreport

Для ручной проверки: касса, приходы, расходы, прибыль.
"""
from django.core.management.base import BaseCommand

from apps.finance.services import (
    cash_movement,
    get_cash_balance,
    total_expense,
    total_income,
)


class Command(BaseCommand):
    help = "Показать кассу, приходы и расходы (за всё время)"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("=== Движение денег ==="))
        self.stdout.write(f"Касса (текущий остаток): {get_cash_balance()} сом")
        self.stdout.write(f"Всего приходов:          {total_income()} сом")
        self.stdout.write(f"Всего расходов:          {total_expense()} сом")
        self.stdout.write(f"Изменение кассы:         {cash_movement()} сом")
        self.stdout.write(
            "\nПрибыль здесь НЕ считается: это движение денег. "
            "Прибыль — на дашборде и в отчётах."
        )
