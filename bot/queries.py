"""Общие обёртки над ORM для хендлеров бота.

ORM синхронный, aiogram асинхронный — поэтому всё через `sync_to_async`.
Сюда выносим то, что нужно больше чем одному сценарию (раньше `_get_products`
и `_get_product_info` были продублированы в sales.py и receipts.py).
"""
from asgiref.sync import sync_to_async


@sync_to_async
def get_products():
    """Активные товары парами (id, название) — для клавиатуры выбора."""
    from apps.catalog.models import Product

    return list(Product.objects.filter(is_active=True).values_list("id", "name"))


@sync_to_async
def get_active_clients():
    """Активные клиенты парами (id, имя).

    Неактивных прячем: в базе их 70+, и списком выбора пользоваться
    невозможно. Признак снимается галочкой в админке.
    """
    from apps.clients.models import Client

    return list(
        Client.objects.filter(is_active=True).order_by("name").values_list("id", "name")
    )


@sync_to_async
def find_clients(text):
    """Поиск клиента по части имени — для «свой вариант» среди неактивных."""
    from apps.clients.models import Client

    return list(
        Client.objects.filter(name__icontains=text.strip())
        .order_by("name")
        .values_list("id", "name")[:20]
    )


@sync_to_async
def create_client(name):
    """Завести клиента из бота. Если такой уже есть — вернуть его."""
    from apps.clients.models import Client

    obj, created = Client.objects.get_or_create(
        name=name.strip(), defaults={"is_active": True}
    )
    if not created and not obj.is_active:
        # Нашёлся среди скрытых — раз им снова пользуются, возвращаем в списки.
        obj.is_active = True
        obj.save(update_fields=["is_active"])
    return obj.id, obj.name, created


@sync_to_async
def get_product_info(pid):
    """Данные товара, нужные хендлерам: название, фасовка, штук в фасовке."""
    from apps.catalog.models import Product

    p = Product.objects.get(pk=pid)
    return {
        "id": p.id,
        "name": p.name,
        "pack_name": p.pack_name,
        "units": p.units_per_pack,
    }
