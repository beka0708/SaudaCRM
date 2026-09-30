from django.db import migrations, models


def fill_revenue(apps, schema_editor):
    """Заполнить снимок выручки для уже существующих позиций.

    Считаем из packs × units_per_pack × price — другого источника нет.
    Для продаж, заведённых через бота, это ТОЧНОЕ значение: фасовка товара
    с момента продажи не менялась. Для строк, залитых импортом, значение
    может разойтись с таблицей заказчика — там «штук в фасовке» за годы
    менялось. Точные цифры для них даёт только повторный импорт: он кладёт
    готовую выручку из колонки «Итого Выручка».

    Проходим построчно, а не одним UPDATE: PostgreSQL не позволяет
    ссылаться в UPDATE на поле через связь (units_per_pack лежит в товаре).
    Строк тут тысячи, так что скорость не важна.
    """
    SaleItem = apps.get_model("sales", "SaleItem")
    batch = []
    for item in SaleItem.objects.select_related("product").iterator(chunk_size=500):
        item.revenue = item.packs * item.product.units_per_pack * item.price_per_unit
        batch.append(item)
        if len(batch) >= 500:
            SaleItem.objects.bulk_update(batch, ["revenue"])
            batch = []
    if batch:
        SaleItem.objects.bulk_update(batch, ["revenue"])


def noop(apps, schema_editor):
    """Откат: поле удаляется целиком, переносить нечего."""


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0003_sale_is_reversed_sale_reversal_reason_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="saleitem",
            name="revenue",
            field=models.DecimalField(
                decimal_places=2, default=0, editable=False, max_digits=14,
                verbose_name="Выручка позиции",
            ),
        ),
        migrations.RunPython(fill_revenue, noop),
    ]
