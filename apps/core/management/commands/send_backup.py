"""Отправить бэкап базы в Telegram. Запускается раз в месяц из cron.

    manage.py send_backup             # последний месячный бэкап
    manage.py send_backup --daily     # последний ежедневный
    manage.py send_backup --dry-run   # показать, что отправили бы

Зачем. Все копии лежат на том же сервере, что и база: умрёт диск — вместе
с ней исчезнут и бэкапы. Копия в Telegram хранится вне сервера, у
владельца в переписке, и достать её можно с телефона.

Файл небольшой (около 70 КБ), лимит Telegram на документ — 50 МБ, так что
упереться в него получится очень нескоро.
"""
import os
from glob import glob

from django.core.management.base import BaseCommand

BACKUP_DIR = os.environ.get("BACKUP_DIR", "/backups")


def latest_backup(kind="monthly"):
    """Самый свежий файл бэкапа. None — если папки нет или она пуста."""
    files = glob(os.path.join(BACKUP_DIR, kind, "*.sql.gz"))
    return max(files, key=os.path.getmtime) if files else None


class Command(BaseCommand):
    help = "Отправить бэкап базы в Telegram"

    def add_arguments(self, parser):
        parser.add_argument("--daily", action="store_true",
                            help="взять ежедневный бэкап вместо месячного")
        parser.add_argument("--dry-run", action="store_true",
                            help="показать файл, не отправляя")

    def handle(self, *args, **options):
        kind = "daily" if options["daily"] else "monthly"
        path = latest_backup(kind)

        if not path:
            # Месячный складывается только 1-го числа — если его ещё нет,
            # лучше отправить свежий ежедневный, чем не отправить ничего.
            path = latest_backup("daily")
            if path:
                self.stdout.write(self.style.WARNING(
                    f"Месячного бэкапа нет, беру ежедневный."))
        if not path:
            self.stdout.write(self.style.ERROR(
                f"Бэкапов не найдено в {BACKUP_DIR}. Папка примонтирована?"))
            return

        size_kb = os.path.getsize(path) / 1024
        name = os.path.basename(path)
        caption = (
            f"💾 <b>Резервная копия базы</b>\n"
            f"{name}\n"
            f"Размер: {size_kb:.0f} КБ\n\n"
            f"<i>Сохраните файл у себя — это копия ВНЕ сервера. "
            f"Если с сервером что-то случится, восстановимся из неё.</i>"
        )

        if options["dry_run"]:
            self.stdout.write(f"Отправили бы: {path} ({size_kb:.0f} КБ)")
            self.stdout.write(caption)
            self.stdout.write(self.style.WARNING("\n[--dry-run] Не отправлено."))
            return

        from apps.core.notifications import broadcast_document

        sent = broadcast_document(path, caption)
        if sent:
            self.stdout.write(self.style.SUCCESS(f"Бэкап отправлен: {sent} получателю(ям)."))
        else:
            self.stdout.write(self.style.WARNING(
                "Никому не отправлено. Проверь галочку «Получает уведомления» "
                "и Telegram ID в админке."))
