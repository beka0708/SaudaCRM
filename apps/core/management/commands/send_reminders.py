"""Напоминания о платежах по нашим кредитам. Запускается ежедневно из cron.

    manage.py send_reminders            # отправить, если есть что напомнить
    manage.py send_reminders --dry-run  # показать текст, не отправляя

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
        payment = o.default_payment or 0
        text = (
            f"⏰ <b>Платёж по кредиту — {when}</b>\n\n"
            f"{o.name}\n"
            f"Дата платежа: {due:%d.%m.%Y}\n"
        )
        if payment:
            text += f"Сумма платежа: <b>{money(payment)} сом</b>\n"
        text += f"Остаток долга: {money(o.remaining)} сом"
        out.append(text)
    return out


class Command(BaseCommand):
    help = "Напомнить о ближайших платежах по кредитам"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="показать текст, не отправляя")

    def handle(self, *args, **options):
        from apps.core.notifications import broadcast

        texts = build_reminders()
        if not texts:
            self.stdout.write("Напоминать нечего.")
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
