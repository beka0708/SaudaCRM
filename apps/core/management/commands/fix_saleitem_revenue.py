"""Починить выручку позиций по сумме продажи.

    manage.py fix_saleitem_revenue          # показать, что изменится
    manage.py fix_saleitem_revenue --yes    # применить

Зачем. Выручка позиции (`SaleItem.revenue`) раньше не хранилась, а
пересчитывалась из packs × units_per_pack × price. «Штук в фасовке» берётся
из справочника ТЕКУЩЕГО товара, а у заказчика фасовки за годы менялись —
поэтому старые продажи считались по новой фасовке и выручка в отчётах
оказалась завышена в разы.

Точный источник есть: `Sale.total`. Для импортированных продаж это цифра
прямо из колонки «Итого Выручка» их таблицы, для продаж из бота — сумма,
посчитанная в момент продажи. Команда приводит позиции к этой сумме:
  - в продаже одна позиция (так импортированы все исторические) — ставим
    ей ровно total;
  - позиций несколько — распределяем total между ними пропорционально
    текущим значениям, чтобы сумма сошлась копейка в копейку.

Себестоимость и кассу НЕ трогаем: они и так хранятся снимками и верны.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Привести выручку позиций в соответствие с суммой продажи"

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true",
                            help="применить (без ключа — только показать)")

    def handle(self, *args, **options):
        from apps.sales.models import Sale

        w = self.stdout.write
        changed, total_before, total_after = [], Decimal("0"), Decimal("0")

        sales = Sale.objects.prefetch_related("items").order_by("created_at")
        for sale in sales:
            items = list(sale.items.all())
            if not items:
                continue
            current = sum((i.revenue for i in items), Decimal("0"))
            total_before += current
            total_after += sale.total

            if current == sale.total:
                continue

            if len(items) == 1:
                items[0].revenue = sale.total
            else:
                # Распределяем пропорционально, остаток от округления
                # отдаём последней позиции — иначе сумма не сойдётся.
                base = current if current else Decimal("1")
                acc = Decimal("0")
                for it in items[:-1]:
                    share = (sale.total * (it.revenue or Decimal("1")) / base)
                    it.revenue = share.quantize(Decimal("0.01"))
                    acc += it.revenue
                items[-1].revenue = sale.total - acc
            changed.extend(items)

        w(self.style.MIGRATE_HEADING("\nВЫРУЧКА ПОЗИЦИЙ"))
        w(f"  продаж всего:        {sales.count()}")
        w(f"  позиций к правке:    {len(changed)}")
        w(f"  сейчас в позициях:   {total_before:,.0f} сом")
        w(f"  станет (= сумма продаж): {total_after:,.0f} сом")
        diff = total_before - total_after
        if diff:
            w(self.style.WARNING(f"  завышение сейчас:    {diff:,.0f} сом"))

        if not changed:
            w(self.style.SUCCESS("\nВсё уже сходится, править нечего."))
            return

        if not options["yes"]:
            w(self.style.WARNING(
                "\n[предпросмотр] Ничего не изменено. "
                "Для применения повторите с ключом --yes"))
            return

        from apps.sales.models import SaleItem

        with transaction.atomic():
            SaleItem.objects.bulk_update(changed, ["revenue"], batch_size=500)
        w(self.style.SUCCESS(f"\nОбновлено позиций: {len(changed)}"))
