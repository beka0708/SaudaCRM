"""Заполнение БД реалистичными демо-данными для показа дашборда.

python manage.py seed_demo

Очищает бизнес-данные (пользователей НЕ трогает) и засевает связный набор:
товары с фасовками, клиенты, приходы, продажи за ~45 дней (с бэкдейтом дат),
расходы, частичные оплаты долгов. Даты проставляются задним числом, чтобы
графики «по дням» и сравнение «месяц vs прошлый» были наполнены.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Заполнить БД демо-данными для дашборда"

    def handle(self, *args, **options):
        from apps.catalog.models import PackagingUnit, Product
        from apps.clients.models import Client
        from apps.debts.models import Debt, DebtPayment
        from apps.debts.services import add_payment
        from apps.finance.models import CashFlow
        from apps.finance.services import add_expense, get_cash_balance
        from apps.sales.models import Sale, SaleItem
        from apps.sales.services import create_sale
        from apps.warehouse.models import Receipt, StockMovement
        from apps.warehouse.services import get_stock, receive_stock

        random.seed(42)
        now = timezone.now()

        # ---------- 1. очистка бизнес-данных ----------
        self.stdout.write("Очистка старых данных…")
        CashFlow.objects.all().delete()
        SaleItem.objects.all().delete()
        DebtPayment.objects.all().delete()
        Debt.objects.all().delete()
        Sale.objects.all().delete()
        Receipt.objects.all().delete()
        StockMovement.objects.all().delete()
        PackagingUnit.objects.all().delete()
        Product.objects.all().delete()
        Client.objects.all().delete()

        # ---------- 2. товары (+ фасовки) ----------
        # (наименование, ед., себестоимость, цена, порог, [(фасовка, в баз.ед.)], старт-остаток)
        specs = [
            ("Сахар", "шт", 60, 85, 20, ("мешок", 50), 6000),
            ("Мука", "шт", 45, 70, 30, ("мешок", 50), 6000),
            ("Масло растительное", "шт", 120, 160, 15, ("коробка", 12), 3000),
            ("Мыло хозяйственное", "шт", 25, 45, 40, ("коробка", 96), 8000),
            ("Салфетки", "шт", 15, 30, 25, ("блок", 12), 4000),
            ("Чай", "шт", 80, 130, 10, ("коробка", 24), 2500),
            ("Рис", "шт", 70, 100, 20, ("мешок", 25), 5000),
            ("Макароны", "шт", 30, 55, 30, None, 4000),
        ]
        products = []
        for name, unit, cost, price, thr, pack, start in specs:
            p = Product.objects.create(
                name=name, base_unit=unit, cost_price=cost, sale_price=price,
                low_stock_threshold=thr,
            )
            if pack:
                PackagingUnit.objects.create(product=p, name=pack[0], quantity_in_base=pack[1])
            receive_stock(p, start, "Стартовый приход")
            products.append(p)
        self.stdout.write(f"Товаров: {len(products)}")

        # ---------- 3. клиенты ----------
        client_names = [
            "Магазин Айгуль", "Магазин Нур", "Точка Береке",
            "Магазин у дома", "ИП Асанов", "Базар №1",
        ]
        clients = [Client.objects.create(name=n, phone="0700000000") for n in client_names]
        self.stdout.write(f"Клиентов: {len(clients)}")

        # ---------- 4. продажи за 45 дней (с бэкдейтом) ----------
        def backdate(sale, dt):
            Sale.objects.filter(pk=sale.pk).update(created_at=dt)
            CashFlow.objects.filter(sale=sale).update(date=dt.date(), created_at=dt)
            Debt.objects.filter(sale=sale).update(created_at=dt)

        def make_sale(dt, force=False):
            items = []
            for _ in range(random.randint(1, 3)):
                p = random.choice(products)
                packs = list(p.packagings.all())
                if packs and random.random() < 0.4:
                    items.append({"product": p, "packaging": packs[0], "count": random.randint(1, 2)})
                else:
                    items.append({"product": p, "packaging": None, "count": random.randint(5, 25)})
            ptype = "debt" if random.random() < 0.3 else "cash"
            client = random.choice(clients) if ptype == "debt" else None
            sale = create_sale(ptype, items, client=client)
            backdate(sale, dt)
            return sale

        sales_count = 0
        for offset in range(45, -1, -1):
            day = now - timedelta(days=offset)
            # чуть больше продаж в будни, меньше по выходным — просто разнообразие
            n = random.randint(1, 4) if offset % 7 not in (5, 6) else random.randint(0, 2)
            for _ in range(n):
                dt = day - timedelta(hours=random.randint(0, 9), minutes=random.randint(0, 59))
                make_sale(dt)
                sales_count += 1
        # гарантируем продажи сегодня и вчера (для KPI и тренда)
        for off in (0, 1):
            for _ in range(2):
                make_sale(now - timedelta(days=off, hours=random.randint(0, 6)))
                sales_count += 1
        self.stdout.write(f"Продаж: {sales_count}")

        # ---------- 5. расходы (текущий и прошлый месяц) ----------
        C = CashFlow.Category
        # аренда — по разу в этом и прошлом месяце
        add_expense(C.RENT, 35000, date=(now - timedelta(days=3)).date(), comment="Аренда")
        add_expense(C.RENT, 35000, date=(now - timedelta(days=33)).date(), comment="Аренда")
        exp_cats = [C.DELIVERY, C.PURCHASE, C.PERSONAL, C.SALARY, C.OTHER_OUT]
        exp_count = 2
        for offset in range(45, -1, -1):
            if random.random() < 0.35:
                cat = random.choice(exp_cats)
                amount = random.choice([1500, 3000, 5000, 8000, 12000])
                add_expense(cat, amount, date=(now - timedelta(days=offset)).date(),
                            comment=cat.label)
                exp_count += 1
        self.stdout.write(f"Расходов: {exp_count}")

        # ---------- 6. частичные оплаты долгов ----------
        pay_count = 0
        for c in clients:
            if c.current_debt > 0 and random.random() < 0.6:
                portion = (c.current_debt * Decimal(random.choice(["0.3", "0.5", "0.7"]))).quantize(Decimal("1"))
                if portion > 0:
                    dt = now - timedelta(days=random.randint(0, 10))
                    payments = add_payment(c, portion, "Оплата долга")
                    for pmt in payments:
                        DebtPayment.objects.filter(pk=pmt.pk).update(created_at=dt)
                        CashFlow.objects.filter(debt_payment=pmt).update(date=dt.date(), created_at=dt)
                        pay_count += 1
        self.stdout.write(f"Оплат долгов: {pay_count}")

        # ---------- 7. пара товаров ниже порога (для виджета «на пополнение») ----------
        # Аккуратно уменьшаем остаток до значения НИЖЕ нормального порога — выглядит
        # естественно (порог не трогаем), корректировкой склада.
        from apps.warehouse.services import adjust_stock

        for p in random.sample(products, 2):
            thr = int(p.low_stock_threshold)
            target = max(1, thr - random.randint(2, max(3, thr // 2)))
            delta = Decimal(target) - get_stock(p)
            if delta != 0:
                adjust_stock(p, delta, "Корректировка остатка (демо)")

        # ---------- итог ----------
        total_debt = sum((c.current_debt for c in clients), Decimal("0"))
        self.stdout.write(self.style.SUCCESS("\n=== ГОТОВО ==="))
        self.stdout.write(f"Касса: {get_cash_balance()} сом")
        self.stdout.write(f"Долги клиентов: {total_debt} сом")
        self.stdout.write(f"Движений денег: {CashFlow.objects.count()}")
        self.stdout.write("Открой /admin/ — дашборд наполнен.")
