"""Импорт данных из рабочей Excel-таблицы Атая.

    manage.py import_excel "/path/Учет товаро Атай.xlsx"            # предпросмотр
    manage.py import_excel "/path/файл.xlsx" --apply                # запись в БД

БЕЗ --apply НИЧЕГО НЕ ПИШЕТСЯ — команда только показывает, что получится,
и сверяет результат с их же листом «Показатели».

Что берём (вариант Б, согласовано): текущее состояние целиком + история
с 2026-01-01 для аналитики. Всю историю с 2024 не тянем.

Источники (колонки ищем ПО ИМЕНИ заголовка, а не по номеру — чтобы вставка
столбца в таблице не ломала импорт):
  «Товары»                  → справочник товаров и штук в фасовке
  «Приход»                  → партии с ненулевым остатком = входящий склад
  «Остатки_долга_под.реал»  → текущие долги клиентов (их рабочая цифра)
  «Исходник»                → продажи с себестоимостью
  «Вернули подреал общий»   → оплаты долгов (ЕДИНСТВЕННЫЙ верный лист:
                              «Подреал» и «Подреал АПИ 2-бот» — его части,
                              импорт всех трёх завысил бы долги втрое)
  «Расход исходник»         → расходы
  «Личные расходы Атай»     → личные расходы
  «Сосотояние оборотных средств» → строка «На счету» = входящая касса

Чего НЕ делаем и почему:
  - историю НЕ проводим через process_sale: FIFO списывал бы из партий,
    которых в таблице нет (партии есть только открытые), и упёрся бы в
    нехватку товара. Себестоимость берём готовую из колонки «Итого Себес»;
  - закупки по партиям НЕ книжим расходом: они уже отражены в «На счету»,
    а их же лист «Показатели» считает расходы БЕЗ закупок;
  - касса сводится одной балансирующей проводкой на 31.12.2025, чтобы
    итоговый остаток совпал с «На счету».
"""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

SINCE_DEFAULT = date(2026, 1, 1)
OPENING_DATE = date(2025, 12, 31)   # дата входящих остатков
DEFAULT_PACK = "мешок"              # в таблице фасовка не указана — поправят в админке

# Строки-итоги, которые лежат вперемешку с клиентами и удваивают суммы.
TOTAL_ROW_MARKERS = ("итого", "всего")
GARBAGE = {"#ref!", "#n/a", "#value!", "none", ""}


def _clean(v):
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in GARBAGE else s


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_date(v):
    """Даты в таблице лежат и как даты, и как строки «08.06.2024»."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _clean(v)[:10]
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt).date()
            return d if d.year > 2000 else None   # отсекает excel-нуль 30.12.1899
        except ValueError:
            pass
    return None


def _aware(d):
    """Дата → datetime на начало дня с таймзоной.

    В проекте USE_TZ=True, и наивный datetime роняет timezone.localdate()
    в проводках («localtime() cannot be applied to a naive datetime»).
    """
    return timezone.make_aware(datetime.combine(d, datetime.min.time()))


def _is_total_row(name):
    low = name.lower()
    return any(m in low for m in TOTAL_ROW_MARKERS)


class Sheet:
    """Лист с доступом к колонкам по имени заголовка."""

    def __init__(self, ws):
        self.ws = ws
        self.rows = list(ws.iter_rows(values_only=True))
        header = self.rows[0] if self.rows else ()
        self.idx = {}
        for i, h in enumerate(header):
            key = _clean(h).lower()
            if key and key not in self.idx:
                self.idx[key] = i

    def col(self, *names):
        for n in names:
            i = self.idx.get(n.lower())
            if i is not None:
                return i
        raise CommandError(
            f"В листе «{self.ws.title}» не нашёл колонку {names[0]!r}. "
            f"Есть: {list(self.idx)[:12]}"
        )

    def data(self):
        for r in self.rows[1:]:
            if any(c is not None and str(c).strip() != "" for c in r):
                yield r


# --- категории расходов -------------------------------------------------
# Их свободный текст сводим к нашим категориям, а ОРИГИНАЛ всегда кладём в
# комментарий: ничего не теряем, при желании потом пересоберём детальнее.
def map_expense(text):
    from apps.finance.models import CashFlow

    t = text.lower()
    if "аренда" in t:
        return CashFlow.Category.RENT
    if t.startswith("зп") or "зарплат" in t:
        return CashFlow.Category.SALARY
    if any(k in t for k in ("топливо", "стоянка", "аммор", "такси", "бензин", "парковка")):
        return CashFlow.Category.DELIVERY
    return CashFlow.Category.OTHER_OUT


class Command(BaseCommand):
    help = "Импорт данных из Excel-таблицы Атая (по умолчанию — предпросмотр)"

    def add_arguments(self, p):
        p.add_argument("path", help="путь к .xlsx")
        p.add_argument("--apply", action="store_true",
                       help="записать в БД (без ключа — только предпросмотр)")
        p.add_argument("--since", default=SINCE_DEFAULT.isoformat(),
                       help=f"импортировать историю с этой даты (по умолч. {SINCE_DEFAULT})")
        p.add_argument("--cash", type=Decimal, default=None,
                       help="фактический остаток кассы. По умолчанию берётся строка "
                            "«На счету» из таблицы, но она заполняется ВРУЧНУЮ и "
                            "часто отстаёт — тогда задайте реальную сумму здесь.")

    def handle(self, *args, **o):
        from openpyxl import load_workbook

        since = _parse_date(o["since"]) or SINCE_DEFAULT
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nИмпорт из {o['path']}\nИстория с {since}, текущее состояние — целиком\n"))

        import warnings
        warnings.filterwarnings("ignore")
        wb = load_workbook(o["path"], data_only=True)
        sheets = {n: Sheet(wb[n]) for n in [
            "Товары", "Приход", "Остатки_долга_под.реал", "Исходник",
            "Вернули подреал общий", "Расход исходник", "Личные расходы Атай",
            "Сосотояние оборотных средств", "Показатели",
        ]}

        plan = self.build_plan(sheets, since)
        if o.get("cash") is not None:
            plan["cash_from_sheet"] = plan["cash_now"]
            plan["cash_now"] = o["cash"]
        self.report(plan, since)

        if not o["apply"]:
            self.stdout.write(self.style.WARNING(
                "\n[предпросмотр] В БД ничего не записано. "
                "Для записи повторите с ключом --apply"))
            return

        self.apply(plan, since)

    # ---------- разбор ----------

    def build_plan(self, S, since):
        plan = {"warnings": []}

        # товары: имя + штук в фасовке
        products = {}
        sh = S["Товары"]
        for r in sh.data():
            name, upp = _clean(r[0]), _num(r[1])
            if name and not _is_total_row(name):
                products[name] = int(upp or 1)
        plan["products"] = products

        # открытые партии = входящий склад
        sh = S["Приход"]
        c_prod = sh.col("Товар")
        c_left = sh.col("Кол-во_(меш.блок)_осталось")
        c_cost = sh.col("Цена_за_1_единцу_себес")
        c_date = sh.col("Дата_прихода")
        c_lot = sh.col("Партия")
        batches = []
        for r in sh.data():
            name, left, cost = _clean(r[c_prod]), _num(r[c_left]), _num(r[c_cost])
            if not name or not left or left <= 0 or not cost:
                continue
            batches.append({
                "product": name, "packs": int(left),
                "cost": Decimal(str(round(cost, 2))),
                "date": _parse_date(r[c_date]) or since,
                "lot": _clean(r[c_lot]),
            })
        plan["batches"] = batches

        # текущие долги клиентов (их рабочая цифра)
        sh = S["Остатки_долга_под.реал"]
        c_name, c_rest = sh.col("Имена"), sh.col("Остаток")
        debts_now = {}
        for r in sh.data():
            name, rest = _clean(r[c_name]), _num(r[c_rest])
            if name and not _is_total_row(name) and rest is not None:
                debts_now[name] = Decimal(str(round(rest, 2)))
        plan["debts_now"] = debts_now

        # продажи с даты `since`
        sh = S["Исходник"]
        ci = {k: sh.col(k) for k in ["Дата", "Товар", "Нал/по реал", "Кому под реал",
                                     "Кол-во", "Цена за ед", "Итого Выручка", "Итого Себес"]}
        sales, skipped = [], 0
        for r in sh.data():
            d = _parse_date(r[ci["Дата"]])
            prod = _clean(r[ci["Товар"]])
            packs = _num(r[ci["Кол-во"]])
            rev = _num(r[ci["Итого Выручка"]])
            if not d or not prod or not packs or rev is None:
                skipped += 1
                continue
            if d < since:
                continue
            kind = _clean(r[ci["Нал/по реал"]]).lower()
            sales.append({
                "date": d, "product": prod, "packs": int(packs),
                "price": Decimal(str(round(_num(r[ci["Цена за ед"]]) or 0, 2))),
                "revenue": Decimal(str(round(rev, 2))),
                "cogs": Decimal(str(round(_num(r[ci["Итого Себес"]]) or 0, 2))),
                "debt": kind == "под.реал",
                "client": _clean(r[ci["Кому под реал"]]),
            })
        plan["sales"], plan["sales_skipped"] = sales, skipped

        # оплаты долгов
        sh = S["Вернули подреал общий"]
        c_when, c_amt, c_who = sh.col("Когда"), sh.col("На какую сумму вернул"), sh.col("Кто")
        pays = []
        for r in sh.data():
            d, amt, who = _parse_date(r[c_when]), _num(r[c_amt]), _clean(r[c_who])
            if not d or not who or _is_total_row(who) or not amt or amt <= 0:
                continue
            if d >= since:
                pays.append({"date": d, "client": who, "amount": Decimal(str(round(amt, 2)))})
        plan["payments"] = pays

        # расходы
        expenses = []
        for sheet_name, personal in (("Расход исходник", False), ("Личные расходы Атай", True)):
            sh = S[sheet_name]
            c_d = sh.col("Дата расхода")
            c_what = sh.col("На что рассход")
            c_what2 = sh.col("На что рассход 2")
            c_sum = sh.col("Сумма")
            for r in sh.data():
                d, amt = _parse_date(r[c_d]), _num(r[c_sum])
                if not d or d < since or not amt or amt <= 0:
                    continue
                what = _clean(r[c_what])
                # «Свой вариант» — значит настоящее название лежит в соседней колонке
                if what.lower() == "свой вариант":
                    what = _clean(r[c_what2]) or what
                expenses.append({"date": d, "amount": Decimal(str(round(amt, 2))),
                                 "what": what, "personal": personal})
        plan["expenses"] = expenses

        # входящая касса («На счету»)
        cash = None
        for r in S["Сосотояние оборотных средств"].data():
            if _clean(r[0]).lower().startswith("на счету"):
                cash = _num(r[1])
                break
        if cash is None:
            plan["warnings"].append("не нашёл строку «На счету» — входящая касса будет 0")
        plan["cash_now"] = Decimal(str(round(cash or 0, 2)))

        # эталон для сверки
        sh = S["Показатели"]
        c_m, c_rev, c_cogs = sh.col("Месяц"), sh.col("Выручка_итого"), sh.col("Итого_себес")
        c_exp, c_prof, c_dt = sh.col("Расходы_итого"), sh.col("Чистый_доход"), sh.col("Дата_лукер")
        ref = {}
        for r in sh.data():
            d = _parse_date(r[c_dt])
            if d and d >= since.replace(day=1):
                ref[(d.year, d.month)] = {
                    "revenue": _num(r[c_rev]) or 0, "cogs": _num(r[c_cogs]) or 0,
                    "expenses": _num(r[c_exp]) or 0, "profit": _num(r[c_prof]) or 0}
        plan["reference"] = ref

        # входящие долги на начало периода
        ds, pp = defaultdict(Decimal), defaultdict(Decimal)
        for s in sales:
            if s["debt"] and s["client"]:
                ds[s["client"]] += s["revenue"]
        for p in pays:
            pp[p["client"]] += p["amount"]
        opening = {}
        for name, cur in debts_now.items():
            val = cur - ds.get(name, 0) + pp.get(name, 0)
            if val < 0:
                plan["warnings"].append(f"входящий долг «{name}» отрицательный ({val:,.0f}) — обнулён")
                val = Decimal("0")
            if val > 0:
                opening[name] = val
        # клиенты, которые есть только в продажах/оплатах
        for name in set(ds) | set(pp):
            opening.setdefault(name, Decimal("0"))
        plan["opening_debts"] = opening

        # товары, встреченные в продажах, но не в справочнике
        unknown = {s["product"] for s in sales} - set(products)
        if unknown:
            plan["warnings"].append(f"товары есть в продажах, но НЕ в справочнике: {sorted(unknown)}")
        return plan

    # ---------- предпросмотр ----------

    def report(self, plan, since):
        w = self.stdout.write
        w(self.style.MIGRATE_HEADING("ЧТО БУДЕТ СОЗДАНО"))
        w(f"  товаров:              {len(plan['products'])}")
        w(f"  партий (склад):       {len(plan['batches'])}  "
          f"({sum(b['packs'] for b in plan['batches']):,} фасовок)")
        w(f"  клиентов:             {len(set(plan['debts_now']) | set(plan['opening_debts']))}")
        w(f"  входящих долгов:      {len([v for v in plan['opening_debts'].values() if v > 0])}  "
          f"на сумму {sum(plan['opening_debts'].values()):,.0f}")
        w(f"  продаж с {since}:  {len(plan['sales'])}  "
          f"(пропущено мусорных строк: {plan['sales_skipped']})")
        w(f"  оплат долгов:         {len(plan['payments'])}")
        w(f"  расходов:             {len(plan['expenses'])}")
        if "cash_from_sheet" in plan:
            w(f"  входящая касса:       {plan['cash_now']:,.0f} сом  "
              f"(задана вручную; в таблице {plan['cash_from_sheet']:,.0f})")
        else:
            w(f"  входящая касса:       {plan['cash_now']:,.0f} сом  (строка «На счету»)")

        w(self.style.MIGRATE_HEADING("\nСВЕРКА С ИХ ЛИСТОМ «Показатели»"))
        by_month = defaultdict(lambda: {"revenue": Decimal(0), "cogs": Decimal(0)})
        for s in plan["sales"]:
            k = (s["date"].year, s["date"].month)
            by_month[k]["revenue"] += s["revenue"]
            by_month[k]["cogs"] += s["cogs"]
        exp_month = defaultdict(Decimal)
        for e in plan["expenses"]:
            exp_month[(e["date"].year, e["date"].month)] += e["amount"]

        w(f"  {'МЕСЯЦ':<9}{'выручка':>12}{'эталон':>12}{'Δ':>9}"
          f"{'себес':>12}{'эталон':>12}{'Δ':>9}")
        for k in sorted(set(by_month) | set(plan["reference"])):
            ref = plan["reference"].get(k)
            if not ref or (not ref["revenue"] and k not in by_month):
                continue
            mine = by_month.get(k, {"revenue": Decimal(0), "cogs": Decimal(0)})
            dr = float(mine["revenue"]) - ref["revenue"]
            dc = float(mine["cogs"]) - ref["cogs"]
            flag = "" if abs(dr) < 1 else "  ←"
            w(f"  {k[1]:02d}.{k[0]}{float(mine['revenue']):>12,.0f}{ref['revenue']:>12,.0f}"
              f"{dr:>9,.0f}{float(mine['cogs']):>12,.0f}{ref['cogs']:>12,.0f}{dc:>9,.0f}{flag}")

        if plan["warnings"]:
            w(self.style.WARNING("\nПРЕДУПРЕЖДЕНИЯ"))
            for x in plan["warnings"]:
                w(f"  • {x}")
        w(self.style.WARNING(
            f"\n  фасовка у всех товаров будет «{DEFAULT_PACK}» — в таблице её нет, "
            f"поправьте в админке ({len(plan['products'])} товаров)"))

    # ---------- запись ----------

    @transaction.atomic
    def apply(self, plan, since):
        from apps.catalog.models import Product
        from apps.clients.models import Client
        from apps.debts.models import Debt
        from apps.debts.services import add_payment, create_debt
        from apps.finance.models import CashFlow
        from apps.finance.services import get_cash_balance, record_cash_flow
        from apps.sales.models import Sale, SaleItem
        from apps.warehouse.models import Batch

        w = self.stdout.write
        if Sale.objects.exists() or Batch.objects.exists():
            raise CommandError(
                "В базе уже есть продажи или партии. Импорт рассчитан на ЧИСТУЮ базу — "
                "иначе данные задвоятся. Очистите базу и повторите.")

        opening_dt = _aware(OPENING_DATE)

        products = {}
        for name, upp in plan["products"].items():
            products[name] = Product.objects.create(
                name=name, pack_name=DEFAULT_PACK, units_per_pack=upp)
        w(f"  товаров: {len(products)}")

        # Партии создаём через bulk_create, в обход Batch.save(): он бы списал
        # закупку из кассы, а эти закупки уже отражены во входящем остатке.
        Batch.objects.bulk_create([
            Batch(product=products[b["product"]], cost_per_unit=b["cost"],
                  packs_received=b["packs"], packs_remaining=b["packs"],
                  comment=b["lot"] or "Входящий остаток",
                  created_at=_aware(b["date"]))
            for b in plan["batches"] if b["product"] in products
        ])
        w(f"  партий: {Batch.objects.count()}")

        clients = {}
        for name in sorted(set(plan["debts_now"]) | set(plan["opening_debts"])):
            clients[name] = Client.objects.create(name=name)
        w(f"  клиентов: {len(clients)}")

        for name, amount in plan["opening_debts"].items():
            if amount > 0:
                create_debt(clients[name], amount, comment="Входящий долг на 01.01.2026",
                            created_at=opening_dt)
        w(f"  входящих долгов: {Debt.objects.count()}")

        # События 2026 в хронологическом порядке: оплата может гасить только
        # тот долг, который к этому моменту уже существует.
        events = [("sale", s["date"], s) for s in plan["sales"]]
        events += [("pay", p["date"], p) for p in plan["payments"]]
        events.sort(key=lambda e: (e[1], 0 if e[0] == "sale" else 1))

        n_sale = n_pay = 0
        for kind, d, item in events:
            dt = _aware(d)
            if kind == "sale":
                if item["product"] not in products:
                    continue
                client = clients.get(item["client"]) if item["client"] else None
                sale = Sale.objects.create(
                    client=client,
                    payment_type=Sale.PaymentType.DEBT if item["debt"] else Sale.PaymentType.CASH,
                    total=item["revenue"], is_processed=True,
                    comment="Импорт из Excel", created_at=dt)
                SaleItem.objects.create(
                    sale=sale, product=products[item["product"]], packs=item["packs"],
                    price_per_unit=item["price"], cogs=item["cogs"])
                # FIFO не трогаем: партий за историю в таблице нет, себестоимость
                # взята готовой. Проводки книжим вручную.
                if item["debt"] and client:
                    create_debt(client, item["revenue"], sale=sale,
                                comment=f"Реализация по продаже #{sale.pk}", created_at=dt)
                else:
                    record_cash_flow(CashFlow.Direction.IN, CashFlow.Category.SALE,
                                     item["revenue"], date=d,
                                     comment=f"Продажа #{sale.pk}", sale=sale)
                n_sale += 1
            else:
                client = clients.get(item["client"])
                if client:
                    add_payment(client, item["amount"], comment="Импорт из Excel", created_at=dt)
                    n_pay += 1
        w(f"  продаж: {n_sale}, оплат: {n_pay}")

        for e in plan["expenses"]:
            cat = CashFlow.Category.PERSONAL if e["personal"] else map_expense(e["what"])
            record_cash_flow(CashFlow.Direction.OUT, cat, e["amount"],
                             date=e["date"], comment=e["what"] or "Импорт из Excel")
        w(f"  расходов: {len(plan['expenses'])}")

        # Одна балансирующая проводка, чтобы касса сошлась с их «На счету».
        diff = plan["cash_now"] - get_cash_balance()
        if diff:
            record_cash_flow(
                CashFlow.Direction.IN if diff > 0 else CashFlow.Direction.OUT,
                CashFlow.Category.INVESTMENT if diff > 0 else CashFlow.Category.OTHER_OUT,
                abs(diff), date=OPENING_DATE,
                comment="Входящий остаток на 01.01.2026")
        w(f"  касса сведена: {get_cash_balance():,.0f} сом "
          f"(балансирующая проводка {diff:+,.0f})")
        w(self.style.SUCCESS("\nИмпорт завершён."))
