"""Кросс-доменные сервисы.

Здесь живёт то, что не принадлежит одному приложению. Пока это лента
последних операций — она собирает продажи, приходы и оплаты в один список,
чтобы бот мог предложить «выбери, что отменить», не заставляя человека
помнить номер документа.
"""
from datetime import timedelta

from django.utils import timezone


def humanize_dt(dt) -> str:
    """«только что» / «5 мин назад» / «сегодня 14:30» / «вчера 16:40» / «12.09 10:15».

    Атай отменяет ошибку почти сразу, поэтому у свежих операций относительное
    время читается быстрее, чем дата.
    """
    delta = timezone.now() - dt
    if delta < timedelta(minutes=1):
        return "только что"
    if delta < timedelta(hours=1):
        return f"{int(delta.total_seconds() // 60)} мин назад"
    local = timezone.localtime(dt)
    today = timezone.localdate()
    if local.date() == today:
        return f"сегодня {local:%H:%M}"
    if local.date() == today - timedelta(days=1):
        return f"вчера {local:%H:%M}"
    return f"{local:%d.%m %H:%M}"


def recent_operations(limit=8) -> list[dict]:
    """Последние НЕсторнированные операции всех типов, свежие первыми.

    Каждый элемент: kind ("sale"/"batch"/"payment"), id, dt, icon, title, detail.
    Уже сторнированные не показываем — отменять их нечего.
    """
    from apps.analytics.services import money
    from apps.catalog.services import pack_label
    from apps.debts.models import DebtPayment
    from apps.sales.models import Sale
    from apps.warehouse.models import Batch

    ops = []

    sales = (
        Sale.objects.active()
        .filter(is_processed=True)
        .select_related("client")
        .order_by("-created_at")[:limit]
    )
    for s in sales:
        detail = f"{money(s.total)} сом · {s.get_payment_type_display()}"
        if s.client_id:
            detail += f" · {s.client.name}"
        ops.append({
            "kind": "sale", "id": s.pk, "dt": s.created_at,
            "icon": "🧾", "title": f"Продажа #{s.pk}", "detail": detail,
        })

    batches = (
        Batch.objects.filter(is_reversed=False)
        .select_related("product")
        .order_by("-created_at")[:limit]
    )
    for b in batches:
        packs = b.packs_received
        ops.append({
            "kind": "batch", "id": b.pk, "dt": b.created_at,
            "icon": "📥", "title": f"Приход · {b.product.name}",
            "detail": f"{packs} {pack_label(b.product.pack_name, packs)}",
        })

    payments = (
        DebtPayment.objects.filter(is_reversed=False, debt__is_reversed=False)
        .select_related("debt__client")
        .order_by("-created_at")[:limit]
    )
    for p in payments:
        ops.append({
            "kind": "payment", "id": p.pk, "dt": p.created_at,
            "icon": "💰", "title": f"Оплата · {p.debt.client.name}",
            "detail": f"{money(p.amount)} сом",
        })

    ops.sort(key=lambda o: o["dt"], reverse=True)
    return ops[:limit]
