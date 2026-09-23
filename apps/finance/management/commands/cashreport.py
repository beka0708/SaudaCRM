"""Быстрая сводка по деньгам: python manage.py cashreport

Для ручной проверки: касса, приходы, расходы, прибыль.
"""
from django.core.management.base import BaseCommand

from apps.finance.services import (
    get_cash_balance,
    profit,
    total_expense,
    total_income,
)


class Command(BaseCommand):
    help = "Показать кассу, приходы, расходы и прибыль (за всё время)"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("=== Финансовая сводка ==="))
        self.stdout.write(f"Касса (текущий остаток): {get_cash_balance()} сом")
        self.stdout.write(f"Всего приходов:          {total_income()} сом")
        self.stdout.write(f"Всего расходов:          {total_expense()} сом")
        self.stdout.write(f"Прибыль (приход−расход): {profit()} сом")
