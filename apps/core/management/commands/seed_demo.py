"""Демо-данные под партионную модель (фасовки + FIFO).

python manage.py seed_demo

Очищает бизнес-данные (пользователей не трогает) и засевает: товары (одна
фасовка), по 2 ПАРТИИ с разной себестоимостью (для наглядного FIFO), продажи
за ~45 дней (кол-во в фасовках + цена за штуку), расходы, частичные оплаты.
Даты проставляются задним числом.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Заполнить БД демо-данными (партионная модель)"

    def handle(self, *args, **options):
        from apps.catalog.models import Product
        from apps.clients.models import Client
        from apps.debts.models import Debt, DebtPayment
        from apps.debts.services import add_payment
        from apps.finance.models import CashFlow
        from apps.finance.services import add_expense, get_cash_balance
        from apps.sales.models import Sale, SaleItem
        from apps.sales.services import create_sale
        from apps.warehouse.models import Batch, BatchConsumption
        from apps.warehouse.services import get_stock, receive_batch

        from django.core.exceptions import ValidationError

        random.seed(42)
        now = timezone.now()

        # ---------- очистка ----------
        self.stdout.write("Очистка старых данных…")
        CashFlow.objects.all().delete()
        BatchConsumption.objects.all().delete()
        SaleItem.objects.all().delete()
        DebtPayment.objects.all().delete()
        Debt.objects.all().delete()
        Sale.objects.all().delete()
        Batch.objects.all().delete()
        Product.objects.all().delete()
        Client.objects.all().delete()

        # ---------- товары ----------
        # (имя, база, фасовка, штук/фасовку, порог(фасовок), cost1, cost2, цена/шт)
        specs = [
            ("Сахар", "шт", "мешок", 50, 5, 55, 60, 85),
            ("Мука", "шт", "мешок", 50, 5, 42, 45, 70),
            ("Масло растительное", "шт", "коробка", 12, 4, 120, 130, 165),
            ("Мыло хозяйственное", "шт", "коробка", 96, 6, 22, 25, 42),
            ("Салфетки", "шт", "блок", 12, 8, 12, 15, 28),
            ("Чай", "шт", "коробка", 24, 4, 80, 90, 135),
            ("Рис", "шт", "мешок", 25, 5, 70, 78, 105),
            ("Макароны", "шт", "коробка", 20, 6, 30, 33, 55),
        ]
        products = {}
        sell_price = {}
        for name, base, pack, upp, thr, c1, c2, price in specs:
            p = Product.objects.create(
                name=name, base_unit=base, pack_name=pack, units_per_pack=upp,
                low_stock_threshold=thr,
            )
            products[name] = p
            sell_price[name] = price
            # две партии: старая (дешевле) и новая (дороже) — для FIFO
            for cost, offset, packs in ((c1, 52, 40), (c2, 26, 40)):
                dt = now - timedelta(days=offset, hours=random.randint(0, 6))
                # Дату прихода задаём сразу — расход «Закупка» ляжет в кассу той
                # же датой (Batch.save), доправлять задним числом больше нечего.
                receive_batch(p, packs, cost, comment=f"Партия {name}", created_at=dt)
        self.stdout.write(f"Товаров: {len(products)} (по 2 партии)")

        # ---------- клиенты ----------
        client_names = ["Магазин Айгуль", "Магазин Нур", "Точка Береке",
                        "Магазин у дома", "ИП Асанов", "Базар №1"]
        clients = [Client.objects.create(name=n, phone="0700000000") for n in client_names]
        self.stdout.write(f"Клиентов: {len(clients)}")

        # ---------- стартовый капитал (иначе касса в минусе из-за закупок) ----------
        from apps.finance.services import record_cash_flow

        record_cash_flow(
            CashFlow.Direction.IN, CashFlow.Category.INVESTMENT, 1500000,
            date=(now - timedelta(days=55)).date(), comment="Стартовый капитал",
        )

        # ---------- продажи за 45 дней ----------
        def make_sale(dt):
            names = random.sample(list(products), random.randint(1, 3))
            items = []
            for nm in names:
                p = products[nm]
                base = sell_price[nm]
                price = base + random.randint(-3, 6)  # у разных клиентов чуть разная цена
                items.append({"product": p, "packs": random.randint(1, 3), "price_per_unit": price})
            ptype = "debt" if random.random() < 0.3 else "cash"
            client = random.choice(clients) if ptype == "debt" else None
            try:
                # created_at протягивается в кассу и в долг — бэкдейтить нечего.
                create_sale(ptype, items, client=client, created_at=dt)
            except ValidationError:
                return False  # не хватило на складе — пропускаем
            return True

        sales_count = 0
        for offset in range(45, -1, -1):
            day = now - timedelta(days=offset)
            n = random.randint(1, 3) if offset % 7 not in (5, 6) else random.randint(0, 1)
            for _ in range(n):
                dt = day - timedelta(hours=random.randint(0, 9), minutes=random.randint(0, 59))
                if make_sale(dt):
                    sales_count += 1
        for off in (0, 1):  # гарантируем продажи сегодня/вчера
            for _ in range(2):
                if make_sale(now - timedelta(days=off, hours=random.randint(0, 6))):
                    sales_count += 1
        self.stdout.write(f"Продаж: {sales_count}")

        # ---------- расходы (аренда/прочее) ----------
        C = CashFlow.Category
        add_expense(C.RENT, 35000, date=(now - timedelta(days=3)).date(), comment="Аренда")
        add_expense(C.RENT, 35000, date=(now - timedelta(days=33)).date(), comment="Аренда")
        exp_count = 2
        for offset in range(45, -1, -1):
            if random.random() < 0.3:
                cat = random.choice([C.DELIVERY, C.PERSONAL, C.SALARY, C.OTHER_OUT])
                add_expense(cat, random.choice([1500, 3000, 5000, 8000]),
                            date=(now - timedelta(days=offset)).date(), comment=cat.label)
                exp_count += 1
        self.stdout.write(f"Расходов (кроме закупок): {exp_count}")

        # ---------- частичные оплаты долгов ----------
        pay_count = 0
        for c in clients:
            if c.current_debt > 0 and random.random() < 0.6:
                portion = (c.current_debt * Decimal(random.choice(["0.3", "0.5"]))).quantize(Decimal("1"))
                if portion > 0:
                    dt = now - timedelta(days=random.randint(0, 10))
                    pay_count += len(add_payment(c, portion, "Оплата долга", created_at=dt))
        self.stdout.write(f"Оплат долгов: {pay_count}")

        # ---------- пара товаров ниже порога ----------
        for p in random.sample(list(products.values()), 2):
            p.low_stock_threshold = get_stock(p) + 3
            p.save(update_fields=["low_stock_threshold"])

        self.stdout.write(self.style.SUCCESS("\n=== ГОТОВО ==="))
        self.stdout.write(f"Касса: {get_cash_balance()} сом")
        self.stdout.write(f"Движений денег: {CashFlow.objects.count()}")
        self.stdout.write("Открой /admin/ — дашборд наполнен.")
