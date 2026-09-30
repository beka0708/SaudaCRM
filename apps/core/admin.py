"""Общие миксины админки.

`LedgerDocumentMixin` — для «документов» учёта (продажа, приход партии, долг,
оплата, движение кассы). Такой документ уже отражён в кассе и на складе, а
удаление строки НЕ откатывает ни то, ни другое: остаток не вернётся в партию,
приход денег останется висеть. Поэтому удаление закрыто на уровне админки —
исправляем ошибки сторнирующей операцией, а не «удалить и завести заново».
"""
from django.contrib import admin  # noqa: F401


class LedgerDocumentMixin:
    """Документ учёта: создавать/смотреть можно, удалять — нет."""

    def has_delete_permission(self, request, obj=None):
        return False


class ActiveFilter(admin.SimpleListFilter):
    """Фильтр «Активные», включённый ПО УМОЛЧАНИЮ.

    Обычный BooleanFieldListFilter показывает сначала всё, а неактивных
    записей со временем становится больше, чем рабочих, и список выбора
    превращается в свалку. Здесь по умолчанию показываются только
    активные, но «Все» остаётся одним кликом.
    """

    title = "Активность"
    parameter_name = "active"

    def lookups(self, request, model_admin):
        return (("all", "Все"), ("no", "Только неактивные"))

    def queryset(self, request, queryset):
        if self.value() == "all":
            return queryset
        if self.value() == "no":
            return queryset.filter(is_active=False)
        return queryset.filter(is_active=True)

    def choices(self, changelist):
        # Подсвечиваем «Активные» как выбранный пункт, когда параметра нет.
        yield {
            "selected": self.value() is None,
            "query_string": changelist.get_query_string(remove=[self.parameter_name]),
            "display": "Только активные",
        }
        for lookup, title in self.lookup_choices:
            yield {
                "selected": self.value() == str(lookup),
                "query_string": changelist.get_query_string({self.parameter_name: lookup}),
                "display": title,
            }
