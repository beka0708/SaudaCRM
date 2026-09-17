"""Админка раздела «warehouse» (партионный учёт)."""
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from apps.core.admin import LedgerDocumentMixin

from .models import Batch, BatchConsumption
from .services import reverse_batch


@admin.register(Batch)
class BatchAdmin(LedgerDocumentMixin, ModelAdmin):
    """Приход партии: товар + кол-во фасовок + себестоимость/шт.

    При сохранении закупка автоматически спишется из кассы. После создания
    партия — «документ», поля не редактируем (остаток меняется продажами).
    Дату прихода можно задать при создании — оприходовать задним числом.
    """

    list_display = ("created_at", "product", "cost_per_unit", "packs_received",
                    "packs_remaining", "status", "comment")
    list_filter = ("product", "is_reversed")
    search_fields = ("product__name", "comment")
    autocomplete_fields = ("product",)
    date_hierarchy = "created_at"

    @admin.display(description="Статус", ordering="is_reversed")
    def status(self, obj):
        if obj.is_reversed:
            return format_html('<span style="color:#dc2626;font-weight:600">СТОРНО</span>')
        return "—"

    def get_readonly_fields(self, request, obj=None):
        base = ("packs_remaining",)
        # После создания дату не меняем: она уже отражена в дате расхода
        # «Закупка» в кассе и задаёт порядок FIFO.
        if obj is not None:
            base += ("product", "cost_per_unit", "packs_received", "comment", "created_at")
        if obj is not None and obj.is_reversed:
            base += ("is_reversed", "reversed_at", "reversed_by", "reversal_reason")
        return base

    @admin.action(description="Сторнировать (отменить приход)")
    def reverse_action(self, request, queryset):
        """Отмена прихода — только пока из партии ничего не продано."""
        done = 0
        for batch in queryset:
            try:
                reverse_batch(batch, user=request.user, reason="Сторно из админки")
                done += 1
            except ValidationError as exc:
                self.message_user(
                    request,
                    f"Партия #{batch.pk}: {'; '.join(exc.messages)}",
                    level=messages.ERROR,
                )
        if done:
            self.message_user(
                request, f"Сторнировано приходов: {done}", level=messages.SUCCESS
            )

    actions = ["reverse_action"]


@admin.register(BatchConsumption)
class BatchConsumptionAdmin(LedgerDocumentMixin, ModelAdmin):
    """Списания из партий (создаются автоматически при продаже) — только просмотр."""

    list_display = ("created_at", "batch", "sale_item", "packs", "cost_per_unit")
    search_fields = ("batch__product__name",)
    date_hierarchy = "created_at"
    readonly_fields = ("batch", "sale_item", "packs", "cost_per_unit", "created_at")

    def has_add_permission(self, request):
        return False
