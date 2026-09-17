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
