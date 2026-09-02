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


def broadcast(text) -> int:
    """Разослать текст всем получателям. Возвращает число успешных отправок."""
    sent = 0
    for chat_id in _recipients():
        if send_telegram_message(chat_id, text):
            sent += 1
    return sent


def notify_low_stock(product) -> int:
    """Уведомление о низком остатке товара."""
    from apps.catalog.services import fmt_qty, stock_breakdown

    text = (
        "⚠️ <b>Низкий остаток</b>\n"
        f"{product.name}: осталось {stock_breakdown(product)}\n"
        f"Порог пополнения: {fmt_qty(product.low_stock_threshold)} {product.base_unit}"
    )
    return broadcast(text)
