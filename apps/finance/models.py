"""finance: журнал движений денег (касса).

Касса нигде не хранится числом — считается как сумма приходов минус расходов
(event-sourcing, как и остаток на складе). Одна модель CashFlow на все деньги:
приходы (продажа, оплата долга, инвестиции) и расходы (закупка, аренда, личные).
"""
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.core.models import ReversibleDocument


class CashFlow(models.Model):
    class Direction(models.TextChoices):
        IN = "in", "Приход"
        OUT = "out", "Расход"

    class Category(models.TextChoices):
        # --- приходы ---
        SALE = "sale", "Продажа (наличные)"
        DEBT_PAYMENT = "debt_payment", "Оплата долга (реализация)"
        INVESTMENT = "investment", "Инвестиции"
        OTHER_IN = "other_in", "Прочий приход"
        # --- расходы ---
        PURCHASE = "purchase", "Закупка товара"
        DELIVERY = "delivery", "Доставка"
        RENT = "rent", "Аренда"
        SALARY = "salary", "Зарплата"
        PERSONAL = "personal", "Личные расходы (Атай)"
        # Погашение кредита/долга — НЕ расход бизнеса: деньги уходят, но
        # это уменьшение обязательства, а не издержка. Прибыль не трогает
        # (см. analytics.services.operating_expenses).
        LOAN_PAYMENT = "loan_payment", "Погашение кредита / долга"
        OTHER_OUT = "other_out", "Прочий расход"

    direction = models.CharField("Тип", max_length=8, choices=Direction.choices)
    category = models.CharField("Категория", max_length=20, choices=Category.choices)
    # Своя статья расхода из бота: «Сушняк», «Стоянка», «Шоппинг» и т.п.
    # Категория выше остаётся укрупнённой (для кассы и прибыли), а здесь
    # хранится то, что реально выбрал человек — по ней можно фильтровать
    # и группировать, не плодя два десятка значений в Category.
    subcategory = models.CharField("Статья", max_length=64, blank=True)
    amount = models.DecimalField("Сумма", max_digits=14, decimal_places=2)
    date = models.DateField("Дата", default=timezone.localdate)
    comment = models.CharField("Комментарий", max_length=255, blank=True)

    # Ссылки на источник (для авто-проводок из продаж/оплат) — необязательные.
    sale = models.ForeignKey(
        "sales.Sale",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_flows",
        verbose_name="Продажа-источник",
    )
    debt_payment = models.ForeignKey(
        "debts.DebtPayment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_flows",
        verbose_name="Оплата долга-источник",
    )

    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Движение денег"
        verbose_name_plural = "Касса / движения денег"
        ordering = ["-date", "-created_at"]
        indexes = [models.Index(fields=["direction", "date"])]

    def __str__(self):
        sign = "+" if self.direction == self.Direction.IN else "−"
        return f"{sign}{self.amount} ({self.get_category_display()})"

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.direction == self.Direction.IN else -self.amount


class Obligation(models.Model):
    """Наш долг: кредит или заём у человека.

    Отличается от `debts.Debt` направлением: там нам должны клиенты, здесь
    должны МЫ. Погашение уменьшает кассу, но НЕ прибыль — это не расход,
    а уменьшение обязательства.

    Остаток не хранится числом, а считается как начальная сумма минус
    платежи — тот же принцип, что у кассы и склада.
    """

    class Currency(models.TextChoices):
        KGS = "KGS", "сом"
        USD = "USD", "доллар"

    name = models.CharField("Название", max_length=120)
    code = models.SlugField(
        "Код", max_length=32, unique=True,
        help_text="Служебный идентификатор для кнопок бота. Менять не нужно.",
    )
    currency = models.CharField(
        "Валюта", max_length=3, choices=Currency.choices, default=Currency.KGS
    )
    rate = models.DecimalField(
        "Курс к сому", max_digits=10, decimal_places=2, default=1,
        help_text="Для долга в долларах. Заказчик просил фиксированный курс.",
    )
    opening_amount = models.DecimalField(
        "Начальный остаток", max_digits=14, decimal_places=2,
        help_text="В валюте обязательства. От него вычитаются платежи.",
    )
    default_payment = models.DecimalField(
        "Платёж по умолчанию", max_digits=14, decimal_places=2, null=True, blank=True,
        help_text="Если задан, бот гасит эту сумму одним нажатием, без вопросов.",
    )
    allow_charge = models.BooleanField(
        "Можно занимать ещё", default=False,
        help_text="У банковского кредита сумма фиксирована, а личный заём "
        "можно доливать. Если включено — бот покажет кнопку «Занять ещё».",
    )
    is_active = models.BooleanField("Активно", default=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Наш долг / кредит"
        verbose_name_plural = "Наши долги и кредиты"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name}: осталось {self.remaining}"

    def _sum(self, kind) -> Decimal:
        from django.db.models import Sum

        return self.payments.filter(is_reversed=False, kind=kind).aggregate(
            s=Sum("amount"))["s"] or Decimal("0")

    @property
    def paid(self) -> Decimal:
        """Сколько погасили."""
        return self._sum("payment")

    @property
    def charged(self) -> Decimal:
        """Сколько заняли сверх начальной суммы."""
        return self._sum("charge")

    @property
    def remaining(self) -> Decimal:
        """Остаток в валюте обязательства: начальный + занятое − погашенное."""
        return self.opening_amount + self.charged - self.paid

    @property
    def remaining_kgs(self) -> Decimal:
        """Остаток в сомах: для рублёвого долга это он же, для валютного — по курсу."""
        return self.remaining * self.rate


class ObligationPayment(ReversibleDocument):
    """Движение по нашему долгу: погашение или новый заём.

    Погашение уменьшает долг и уводит деньги из кассы. Заём увеличивает
    долг, но кассу НЕ трогает: занимают не всегда деньгами (бывает и
    товаром), а лишний приход в кассе вычищать тяжелее, чем добавить.
    """

    class Kind(models.TextChoices):
        PAYMENT = "payment", "Погашение"
        CHARGE = "charge", "Новый заём"

    kind = models.CharField(
        "Тип", max_length=8, choices=Kind.choices, default=Kind.PAYMENT
    )
    obligation = models.ForeignKey(
        Obligation, on_delete=models.PROTECT, related_name="payments",
        verbose_name="Долг / кредит",
    )
    amount = models.DecimalField(
        "Сумма платежа", max_digits=14, decimal_places=2,
        help_text="В валюте обязательства.",
    )
    rate = models.DecimalField(
        "Курс на момент платежа", max_digits=10, decimal_places=2, default=1,
        help_text="Снимок: потом курс поменяется, а платёж должен остаться как был.",
    )
    comment = models.CharField("Комментарий", max_length=255, blank=True)
    created_at = models.DateTimeField("Дата", default=timezone.now)

    class Meta:
        verbose_name = "Движение по долгу"
        verbose_name_plural = "Движения по нашим долгам"
        ordering = ["-created_at"]

    def __str__(self):
        mark = " (СТОРНО)" if self.is_reversed else ""
        sign = "+" if self.kind == self.Kind.CHARGE else "−"
        return f"{self.obligation.name}: {sign}{self.amount}{mark}"

    @property
    def amount_kgs(self) -> Decimal:
        return self.amount * self.rate

    def save(self, *args, **kwargs):
        creating = self.pk is None
        if creating and not self.rate:
            self.rate = self.obligation.rate
        super().save(*args, **kwargs)
        # Единая точка: погашение сразу уходит расходом из кассы.
        # Заём кассу не трогает — см. комментарий к классу.
        if creating and self.kind == self.Kind.PAYMENT:
            from apps.finance.services import record_cash_flow

            record_cash_flow(
                CashFlow.Direction.OUT,
                CashFlow.Category.LOAN_PAYMENT,
                self.amount_kgs,
                date=timezone.localdate(self.created_at),
                comment=self.comment or f"Погашение: {self.obligation.name}",
                subcategory=self.obligation.name[:64],
            )
