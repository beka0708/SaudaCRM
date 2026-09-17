"""Утренний дайджест в Telegram. Точка входа для cron.

ЗАПУСК ПО РАСПИСАНИЮ (каждый день в 9:00) — строка в crontab:

    0 9 * * * cd /path/to/saudacrm && .venv/bin/python manage.py send_digest >> /var/log/saudacrm-digest.log 2>&1

Поставить: `crontab -e`. Поменять время — первые два числа: «минута час».
Например 08:30 → `30 8 * * *`.

ПРОВЕРИТЬ БЕЗ ОТПРАВКИ (печатает в консоль, в Telegram ничего не уходит):

    .venv/bin/python manage.py send_digest --dry-run
    .venv/bin/python manage.py send_digest --dry-run --date 2026-08-23

Celery сознательно НЕ используем: одна рассылка в сутки на бюджетном сервере
не стоит брокера и отдельного воркера.
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Собрать и разослать утренний дайджест (для cron)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать текст в консоли, НЕ отправляя в Telegram.",
        )
        parser.add_argument(
            "--date",
            help="День для блока выручки, ГГГГ-ММ-ДД. По умолчанию — вчера.",
        )

    def handle(self, *args, **options):
        from apps.core.digest import build_digest, send_digest

        day = None
        if options.get("date"):
            try:
                day = datetime.strptime(options["date"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("Дата должна быть в формате ГГГГ-ММ-ДД, напр. 2026-08-23.")

        if options["dry_run"]:
            from apps.core.digest import build_blocks

            blocks = build_blocks(day)
            for i, block in enumerate(blocks, 1):
                self.stdout.write(self.style.MIGRATE_HEADING(f"\n--- сообщение {i} из {len(blocks)} ---"))
                self.stdout.write(block)
            self.stdout.write(self.style.WARNING("\n[--dry-run] В Telegram НЕ отправлено."))
            return

        sent = send_digest(day)
        if sent:
            self.stdout.write(self.style.SUCCESS(f"Дайджест отправлен: {sent} сообщени(й)."))
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Никому не отправлено. Проверь: у пользователя стоит галочка "
                    "«Получает уведомления», заполнен Telegram ID, и он нажимал /start у бота."
                )
            )
