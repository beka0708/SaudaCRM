"""Очистка бизнес-данных перед повторным импортом.

    manage.py reset_business_data          # ПОКАЗАТЬ, что будет удалено
    manage.py reset_business_data --yes    # удалить

Зачем: импорт из Excel рассчитан на чистую базу (он не сверяет, что уже
есть, а заливает заново — иначе данные задвоятся). Чтобы перелить свежую
выгрузку, business-данные надо сначала снести.

Пользователей, права и настройки Telegram НЕ трогаем: иначе после каждого
перелива пришлось бы заново заводить админа и привязывать бота.

Без --yes команда ничего не удаляет, только показывает. Отдельно
выделяются записи, ПОХОЖИЕ НА РУЧНОЙ ВВОД (без пометки импорта) — это
работа, которой в Excel нет, и терять её обычно нельзя.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

IMPORT_MARK = "Импорт из Excel"


class Command(BaseCommand):
    help = "Удалить бизнес-данные (товары, продажи, долги, касса), сохранив пользователей"

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes", action="store_true",
            help="действительно удалить (без ключа — только показать)",
        )

    def handle(self, *args, **options):
        from apps.catalog.models import Product
        from apps.clients.models import Client
        from apps.debts.models import Debt, DebtPayment
        from apps.finance.models import CashFlow
        from apps.sales.models import Sale, SaleItem
        from apps.warehouse.models import Batch, BatchConsumption

        w = self.stdout.write

        w(self.style.MIGRATE_HEADING("\nБУДЕТ УДАЛЕНО"))
        for model, label in (
            (Product, "товары"), (Client, "клиенты"), (Batch, "партии"),
            (BatchConsumption, "списания из партий"), (Sale, "продажи"),
            (SaleItem, "позиции продаж"), (Debt, "долги"),
            (DebtPayment, "оплаты долгов"), (CashFlow, "движения кассы"),
        ):
            w(f"  {label:22} {model.objects.count():>7}")

        # Записи без пометки импорта — почти наверняка заведены руками
        # через бота или админку. Их в свежей выгрузке нет.
        manual_sales = Sale.objects.exclude(comment=IMPORT_MARK).count()
        manual_pays = DebtPayment.objects.exclude(comment=IMPORT_MARK).count()
        if manual_sales or manual_pays:
            w(self.style.WARNING(
                f"\n⚠ ПОХОЖЕ НА РУЧНОЙ ВВОД: продаж {manual_sales}, оплат {manual_pays}.\n"
                f"  Этих записей в Excel-выгрузке нет — после очистки они пропадут.\n"
                f"  Если это реальная работа, а не тесты — НЕ продолжайте."))

        from apps.users.models import User
        w(f"\nСОХРАНИТСЯ: пользователей {User.objects.count()} "
          f"(с правами и привязкой Telegram)")

        if not options["yes"]:
            w(self.style.WARNING(
                "\n[предпросмотр] Ничего не удалено. "
                "Для удаления повторите с ключом --yes"))
            return

        # Порядок важен: Batch защищён от удаления ссылками из
        # BatchConsumption, Product и Client — ссылками из продаж и долгов.
        with transaction.atomic():
            for model in (CashFlow, BatchConsumption, SaleItem, DebtPayment,
                          Debt, Sale, Batch, Product, Client):
                count, _ = model.objects.all().delete()
                w(f"  удалено {model.__name__}: {count}")

        w(self.style.SUCCESS("\nБаза очищена. Теперь можно импортировать заново."))
