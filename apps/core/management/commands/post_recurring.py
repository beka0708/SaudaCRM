"""Проведение постоянных расходов (бухуслуги, страховка, зарплата).

    manage.py post_recurring                    # провести, если пора
    manage.py post_recurring --dry-run          # показать, что будет, не записывая
    manage.py post_recurring --dry-run --date 2026-10-31   # проверить на дату

Запускается ежедневно из cron вместе с дайджестом: команда сама решает,
наступил ли день проведения, и сама следит, чтобы за месяц расход прошёл
ровно один раз.

Ключ --date удобен, чтобы заранее убедиться в настройке, не дожидаясь конца
месяца: подставляете нужный день и смотрите, что получится.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Записать постоянные расходы за текущий месяц и уведомить в Telegram"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="показать, что будет проведено, но не записывать")
        parser.add_argument("--date",
                            help="считать, что сегодня эта дата (ГГГГ-ММ-ДД)")

    def handle(self, *args, **options):
        from datetime import datetime

        from django.utils import timezone

        from apps.analytics.services import money
        from apps.core.notifications import broadcast
        from apps.finance.services import due_recurring, get_cash_balance, post_recurring

        today = timezone.localdate()
        if options.get("date"):
            try:
                today = datetime.strptime(options["date"], "%Y-%m-%d").date()
            except ValueError:
                self.stderr.write("Дата в формате ГГГГ-ММ-ДД, напр. 2026-10-31")
                return
            self.stdout.write(self.style.MIGRATE_HEADING(f"Считаем, что сегодня {today}\n"))

        items = due_recurring(today)
        if not items:
            self.stdout.write(
                "Проводить нечего — либо день ещё не наступил, либо за этот "
                "месяц расходы уже записаны.\n"
                "Проверить заранее: --dry-run --date ГГГГ-ММ-ДД")
            return

        if options["dry_run"]:
            total = sum(r.amount for r in items)
            for r in items:
                self.stdout.write(f"  {r.name}: {money(r.amount)} сом ({r.get_category_display()})")
            self.stdout.write(self.style.WARNING(
                f"[--dry-run] Не записано. Итого было бы: {money(total)} сом"))
            return

        created = post_recurring(items, today)
        if not created:
            self.stdout.write("Уже проведено другим запуском.")
            return

        total = sum(f.amount for f in created)
        lines = "\n".join(f"• {f.subcategory}: <b>{money(f.amount)} сом</b>" for f in created)
        broadcast(
            f"🔁 <b>Постоянные расходы записаны</b>\n"
            f"за {today:%m.%Y}\n\n"
            f"{lines}\n\n"
            f"Итого: <b>{money(total)} сом</b>\n"
            f"💰 Касса: <b>{money(get_cash_balance())} сом</b>\n\n"
            f"<i>Если сумма изменилась — поправьте в админке, "
            f"раздел «Постоянные расходы».</i>"
        )
        self.stdout.write(self.style.SUCCESS(
            f"Проведено расходов: {len(created)} на {money(total)} сом"))
