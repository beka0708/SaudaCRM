"""Напоминания о платежах по нашим кредитам. Запускается ежедневно из cron.

    manage.py send_reminders                     # отправить, если есть что
    manage.py send_reminders --dry-run           # показать текст, не отправляя
    manage.py send_reminders --dry-run --date 2026-10-26   # проверить на дату

Ключ --date нужен, чтобы убедиться, что напоминание настроено верно, не
дожидаясь самой даты платежа: подставляете день, когда оно должно прийти,
и смотрите текст.

Напоминаем ЗАРАНЕЕ (по умолчанию за 2 дня), чтобы было время подготовить
деньги. Если у обязательства не задан день платежа — оно пропускается.
"""
from datetime import date, timedelta

from django.core.management.base import BaseCommand


def _clamp_day(year, month, day):
    """День месяца, не выходящий за его границы.

    Если указали 31-е, а в месяце 28 дней — берём последний день, иначе
    date() упадёт на несуществующей дате.
    """
    import calendar

    return min(day, calendar.monthrange(year, month)[1])


def _next_payment_date(day, today):
    """Ближайшая дата платежа: это число в текущем месяце или в следующем."""
    this_month = _clamp_day(today.year, today.month, day)
    if this_month >= today.day:
        return today.replace(day=this_month)
    nxt = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    return nxt.replace(day=_clamp_day(nxt.year, nxt.month, day))


def build_reminders(today=None):
    """Список текстов для отправки. Пусто — значит напоминать нечего."""
    from apps.analytics.services import money
    from apps.finance.models import Obligation

    today = today or date.today()
    out = []
    for o in Obligation.objects.filter(is_active=True, payment_day__isnull=False):
        if o.remaining <= 0:
            continue
        due = _next_payment_date(o.payment_day, today)
        days_left = (due - today).days
        if days_left > o.remind_days_before:
            continue
        when = {0: "СЕГОДНЯ", 1: "завтра"}.get(days_left, f"через {days_left} дн.")
        # Валюта берётся из обязательства: долг Ашимжану в долларах, и
        # показать его в сомах значило бы соврать в 87 раз.
        cur = "$" if o.currency == "USD" else "сом"
        payment = o.default_payment or 0
        text = (
            f"⏰ <b>Платёж — {when}</b>\n\n"
            f"<b>{o.name}</b>\n"
            f"Дата платежа: {due:%d.%m.%Y}\n"
        )
        if payment:
            text += f"Сумма платежа: <b>{money(payment)} {cur}</b>\n"
        text += f"Остаток долга: {money(o.remaining)} {cur}"
        if o.currency != "KGS":
            text += f" ({money(o.remaining_kgs)} сом)"
        out.append(text)
    return out


class Command(BaseCommand):
    help = "Напомнить о ближайших платежах по кредитам"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="показать текст, не отправляя")
        parser.add_argument("--date",
                            help="считать, что сегодня эта дата (ГГГГ-ММ-ДД) — "
                                 "для проверки до наступления срока")

    def handle(self, *args, **options):
        from datetime import datetime

        from apps.core.notifications import broadcast

        today = None
        if options.get("date"):
            try:
                today = datetime.strptime(options["date"], "%Y-%m-%d").date()
            except ValueError:
                self.stderr.write("Дата в формате ГГГГ-ММ-ДД, напр. 2026-10-26")
                return
            self.stdout.write(self.style.MIGRATE_HEADING(f"Считаем, что сегодня {today}\n"))

        texts = build_reminders(today)
        if not texts:
            self.stdout.write(
                "Напоминать нечего — ближайшие платежи ещё не скоро.\n"
                "Проверить заранее: --dry-run --date ГГГГ-ММ-ДД")
            return
        for t in texts:
            if options["dry_run"]:
                self.stdout.write(t + "\n")
            else:
                broadcast(t)
        if not options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"Отправлено напоминаний: {len(texts)}"))
        else:
            self.stdout.write(self.style.WARNING("[--dry-run] Не отправлено."))
