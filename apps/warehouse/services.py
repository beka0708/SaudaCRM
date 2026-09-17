"""Бизнес-логика склада: приход партий и списание по FIFO.

Единая точка изменения склада. Количество — в ФАСОВКАХ (целые), себестоимость
и цена — за штуку (базовую единицу).
"""
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from apps.catalog.services import pack_label

from .models import Batch, BatchConsumption


def get_stock(product) -> int:
    """Остаток товара В ФАСОВКАХ = сумма остатков партий."""
    return product.batches.aggregate(s=Sum("packs_remaining"))["s"] or 0


def stock_value(product) -> Decimal:
    """Стоимость остатка по себестоимости (по партиям)."""
    total = Decimal("0")
    for b in product.batches.filter(packs_remaining__gt=0):
        total += b.remaining_value
    return total


def receive_batch(product, packs, cost_per_unit, comment="", created_at=None) -> Batch:
    """Оприходовать партию (создаёт Batch; закупку в кассу книжит Batch.save).

    `created_at` — дата прихода: задаёт и порядок FIFO, и дату расхода
    «Закупка» в кассе. По умолчанию — сейчас.
    """
    fields = {
        "product": product,
        "packs_received": int(packs),
        "cost_per_unit": Decimal(str(cost_per_unit)),
        "comment": comment,
    }
    if created_at is not None:
        fields["created_at"] = created_at
    return Batch.objects.create(**fields)


def consume_fifo(sale_item) -> Decimal:
    """Списать sale_item.packs фасовок по FIFO. Вернуть COGS. Запрет овердрафта.

    Идёт по партиям товара от старых к новым, уменьшает остаток, пишет
    BatchConsumption и суммирует себестоимость реально «съеденных» партий.
    """
    product = sale_item.product
    need = int(sale_item.packs)
    before = get_stock(product)
    if need > before:
        raise ValidationError(
            f"Недостаточно на складе: {product} — нужно {need}, "
            f"есть {before} {pack_label(product.pack_name, before)}."
        )

    upp = product.units_per_pack
    cogs = Decimal("0")
    remaining = need
    # Списание датируем датой продажи — иначе продажа задним числом даст
    # историю списаний «сегодня».
    consumed_at = sale_item.sale.created_at
    for batch in product.batches.filter(packs_remaining__gt=0).order_by("created_at"):
        if remaining <= 0:
            break
        take = min(batch.packs_remaining, remaining)
        batch.packs_remaining -= take
        batch.save(update_fields=["packs_remaining"])
        BatchConsumption.objects.create(
            sale_item=sale_item,
            batch=batch,
            packs=take,
            cost_per_unit=batch.cost_per_unit,
            created_at=consumed_at,
        )
        cogs += Decimal(take * upp) * batch.cost_per_unit
        remaining -= take

    _maybe_notify_low_stock(product, before, before - need)
    return cogs


# ---------- сторно (компенсирующие операции) ----------

@transaction.atomic
def restore_sale_stock(sale) -> int:
    """Вернуть в партии фасовки, списанные продажей. Возвращает сколько вернули.

    Используется при сторно продажи. Списания (`BatchConsumption`) НЕ удаляем —
    они остаются историей; вернуть товар достаточно через `packs_remaining`.
    """
    per_batch = defaultdict(int)
    for batch_id, packs in BatchConsumption.objects.filter(
        sale_item__sale=sale
    ).values_list("batch_id", "packs"):
        per_batch[batch_id] += packs

    for batch_id, packs in per_batch.items():
        # F() обязателен: если из одной партии списались ДВЕ позиции продажи,
        # чтение-изменение-запись в питоне затёрло бы первый возврат.
        Batch.objects.filter(pk=batch_id).update(
            packs_remaining=F("packs_remaining") + packs
        )

    # Страховка от рассинхрона: вернуть в партию больше, чем в неё приходило, нельзя.
    broken = Batch.objects.filter(
        pk__in=per_batch, packs_remaining__gt=F("packs_received")
    ).first()
    if broken:
        raise ValidationError(
            f"Партия #{broken.pk}: возврат превысил приход — сторно отменено."
        )
    return sum(per_batch.values())


@transaction.atomic
def reverse_batch(batch, user=None, reason="") -> Batch:
    """Сторнировать приход партии: убрать её остаток и вернуть деньги в кассу.

    Разрешено, только пока из партии ничего не продано — иначе пришлось бы
    «отбирать» уже проданный товар. Обратная проводка датируется ДАТОЙ ПАРТИИ
    (а не сегодняшним днём), чтобы отчёт за тот период сошёлся в ноль.
    """
    # Переданный объект может быть устаревшим (например, продажа списала из этой
    # партии уже после того, как её прочитали) — сверяемся с БД, иначе проверка
    # «из партии уже продано» пропустит сторно и потеряет товар.
    batch.refresh_from_db()
    if batch.is_reversed:
        return batch

    consumed = batch.packs_received - batch.packs_remaining
    if consumed > 0:
        raise ValidationError(
            f"Из партии уже продано {consumed} "
            f"{pack_label(batch.product.pack_name, consumed)} — "
            f"сторно прихода невозможно. Сначала сторнируйте продажи по этой партии."
        )

    from apps.finance.models import CashFlow
    from apps.finance.services import record_cash_flow

    amount = (
        Decimal(batch.packs_received * batch.product.units_per_pack) * batch.cost_per_unit
    )
    record_cash_flow(
        CashFlow.Direction.IN,
        CashFlow.Category.PURCHASE,
        amount,
        date=timezone.localdate(batch.created_at),
        comment=f"Сторно закупки (партия #{batch.pk}, {batch.product})",
    )

    batch.packs_remaining = 0  # выпадает из остатка, FIFO и стоимости склада
    batch.mark_reversed(user, reason)
    batch.save(
        update_fields=[
            "packs_remaining", "is_reversed", "reversed_at", "reversed_by", "reversal_reason",
        ]
    )
    return batch


def crossed_below_threshold(before, after, threshold) -> bool:
    """Остаток пересёк порог сверху вниз (чтобы не слать уведомление повторно)."""
    return bool(threshold) and before >= threshold and after < threshold


def _maybe_notify_low_stock(product, before, after):
    if not crossed_below_threshold(before, after, product.low_stock_threshold):
        return
    from django.db import transaction

    from apps.core.notifications import notify_low_stock

    transaction.on_commit(lambda: notify_low_stock(product))
