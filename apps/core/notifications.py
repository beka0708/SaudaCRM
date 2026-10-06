"""Уведомления в Telegram.

Отправляем НАПРЯМУЮ в Telegram Bot API по HTTP (токен из .env), а не через
процесс бота — чтобы уведомление уходило из любого места (продажа из бота ИЛИ
из админки), независимо от того, запущен ли runbot. Сбой отправки не должен
ломать бизнес-операцию, поэтому ошибки глушим.

Получатели — сотрудники (User) с галочкой receives_notifications и заполненным
telegram_id. Пока включаем только владельцу (Атай); механизм рассчитан на
нескольких получателей и на будущие типы уведомлений.
"""
import json
import urllib.error
import urllib.request

from decouple import config

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _recipients() -> list[int]:
    from apps.users.models import User

    return list(
        User.objects.filter(
            receives_notifications=True,
            telegram_id__isnull=False,
            is_active=True,
        ).values_list("telegram_id", flat=True)
    )


def send_telegram_message(chat_id, text) -> bool:
    """Отправить одно сообщение. Возвращает True при успехе, иначе False."""
    token = config("BOT_TOKEN", default="")
    if not token:
        return False
    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    ).encode()
    req = urllib.request.Request(
        _API_URL.format(token=token),
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        return True
    except (urllib.error.URLError, OSError):
        # Уведомление не должно ронять бизнес-логику — молча игнорируем сбой.
        return False


def send_telegram_document(chat_id, path, caption="") -> bool:
    """Отправить файл. Собираем multipart вручную, чтобы не тянуть зависимость.

    Нужно для ежемесячной отправки бэкапа: храниться он должен не только
    на сервере — умрёт диск, вместе с базой исчезнут и копии.
    """
    import mimetypes
    import os
    import uuid

    token = config("BOT_TOKEN", default="")
    if not token or not os.path.exists(path):
        return False

    boundary = uuid.uuid4().hex
    name = os.path.basename(path)
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    with open(path, "rb") as fh:
        content = fh.read()

    def part(header, value):
        return (f"--{boundary}\r\n{header}\r\n\r\n".encode() + value + b"\r\n")

    body = part(f'Content-Disposition: form-data; name="chat_id"', str(chat_id).encode())
    if caption:
        body += part('Content-Disposition: form-data; name="caption"', caption.encode())
        body += part('Content-Disposition: form-data; name="parse_mode"', b"HTML")
    body += part(
        f'Content-Disposition: form-data; name="document"; filename="{name}"\r\n'
        f"Content-Type: {ctype}", content)
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        # Файл может быть на пару мегабайт — таймаут больше, чем у сообщений.
        urllib.request.urlopen(req, timeout=60)
        return True
    except (urllib.error.URLError, OSError):
        return False


def broadcast_document(path, caption="") -> int:
    """Разослать файл всем получателям. Возвращает число успешных отправок."""
    return sum(
        1 for chat_id in _recipients()
        if send_telegram_document(chat_id, path, caption)
    )


def broadcast(text) -> int:
    """Разослать текст всем получателям. Возвращает число успешных отправок."""
    sent = 0
    for chat_id in _recipients():
        if send_telegram_message(chat_id, text):
            sent += 1
    return sent


def notify_low_stock(product) -> int:
    """Уведомление о низком остатке товара (в фасовках)."""
    from apps.catalog.services import pack_label, stock_breakdown

    threshold = product.low_stock_threshold
    text = (
        "⚠️ <b>Низкий остаток</b>\n"
        f"{product.name}: осталось {stock_breakdown(product)}\n"
        f"Порог пополнения: {threshold} {pack_label(product.pack_name, threshold)}"
    )
    return broadcast(text)
