"""Админка раздела «sales»."""
from collections import defaultdict

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from apps.catalog.services import pack_label
from apps.core.admin import LedgerDocumentMixin
from apps.warehouse.services import get_stock

from .models import Sale, SaleItem
from .services import process_sale, reverse_sale


class SaleItemInlineFormSet(BaseInlineFormSet):
    """Проверяет остаток ДО сохранения продажи.

    Без этого нехватка товара вылезала из `consume_fifo` уже в `save_related`
    необработанным `ValidationError` — то есть страницей 500 вместо внятного
    «на складе только N». Здесь ошибка показывается прямо в форме.
    """

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        # Проведённую продажу не перепроверяем: её товар уже списан, и остаток
        # в партиях его больше не содержит — сравнение дало бы ложную ошибку.
        if self.instance and self.instance.pk and self.instance.is_processed:
            return

        # Один товар может стоять в нескольких строках — суммируем.
        need = defaultdict(int)
        for form in self.forms:
            data = getattr(form, "cleaned_data", None)
            if not data or data.get("DELETE"):
                continue
            product, packs = data.get("product"), data.get("packs")
            if product and packs:
                need[product] += packs

        for product, packs in need.items():
            available = get_stock(product)
            if packs > available:
                raise ValidationError(
                    f"{product}: на складе только {available} "
                    f"{pack_label(product.pack_name, available)}, а в продаже {packs}."
                )


class SaleItemInline(TabularInline):
    model = SaleItem
    formset = SaleItemInlineFormSet
    extra = 1
    fields = ("product", "packs", "price_per_unit", "cogs")
    autocomplete_fields = ("product",)
    readonly_fields = ("cogs",)

    # После проведения продажи позиции не редактируем (obj = родительская Sale).
    def has_add_permission(self, request, obj):
        return obj is None or not obj.is_processed

    def has_change_permission(self, request, obj=None):
        return obj is None or not obj.is_processed

    def has_delete_permission(self, request, obj=None):
        return obj is None or not obj.is_processed


@admin.register(Sale)
class SaleAdmin(LedgerDocumentMixin, ModelAdmin):
    list_display = ("id", "created_at", "client", "payment_type", "total", "status")
    list_filter = ("payment_type", "is_reversed", "created_at")
    search_fields = ("client__name", "comment")
    autocomplete_fields = ("client",)
    date_hierarchy = "created_at"
    inlines = [SaleItemInline]

    @admin.display(description="Статус", ordering="is_reversed")
    def status(self, obj):
        if obj.is_reversed:
            return format_html(
                '<span style="color:#dc2626;font-weight:600">СТОРНО</span>'
            )
        if not obj.is_processed:
            return format_html('<span style="color:#9ca3af">не проведена</span>')
        return format_html('<span style="color:#16a34a">проведена</span>')

    def get_readonly_fields(self, request, obj=None):
        base = ("total", "is_processed")
        # Проведённая продажа — «документ»: шапку и дату больше не трогаем,
        # иначе дата разъедется с уже созданной проводкой в кассе.
        if obj is not None and obj.is_processed:
            base += ("client", "payment_type", "comment", "created_at")
        if obj is not None and obj.is_reversed:
            base += ("is_reversed", "reversed_at", "reversed_by", "reversal_reason")
        # При создании дату можно задать вручную — провести задним числом.
        return base

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Позиции уже сохранены — проводим продажу. Сторнированную не трогаем.
        if not form.instance.is_reversed:
            process_sale(form.instance)

    @admin.action(description="Сторнировать (отменить продажу)")
    def reverse_action(self, request, queryset):
        """Компенсирующая отмена: товар обратно в партии, деньги/долг назад."""
        done = 0
        for sale in queryset:
            try:
                reverse_sale(sale, user=request.user, reason="Сторно из админки")
                done += 1
            except ValidationError as exc:
                self.message_user(
                    request,
                    f"Продажа #{sale.pk}: {'; '.join(exc.messages)}",
                    level=messages.ERROR,
                )
        if done:
            self.message_user(
                request, f"Сторнировано продаж: {done}", level=messages.SUCCESS
            )

    @admin.action(description="Экспорт в Excel")
    def export_xlsx(self, request, queryset):
        from apps.reports.services import single_sheet_response

        rows = [
            [s.created_at.strftime("%d.%m.%Y"), str(s.client) if s.client else "—",
             s.get_payment_type_display(), float(s.total),
             "сторно" if s.is_reversed else ""]
            for s in queryset.select_related("client")
        ]
        return single_sheet_response(
            "sales.xlsx", "Продажи",
            ["Дата", "Клиент", "Тип оплаты", "Сумма", "Отметка"], rows, money_cols=(4,))

    actions = ["reverse_action", "export_xlsx"]