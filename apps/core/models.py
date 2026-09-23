"""core: базовые миксины моделей.

`ReversibleDocument` — общая часть «сторнируемого документа» (продажа, приход
партии). Документы учёта не удаляются: удаление не откатывало бы ни склад, ни
кассу. Вместо этого документ помечается сторнированным, а его последствия
отменяются КОМПЕНСИРУЮЩИМИ записями (возврат фасовок в партии, обратная
проводка в кассу). Журналы остаются append-only — как и вся модель проекта,
где остаток и касса нигде не хранятся числом, а считаются из движений.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class ReversibleDocument(models.Model):
    """Документ, который можно сторнировать (отменить), но нельзя удалить."""

    is_reversed = models.BooleanField("Сторнирован", default=False, editable=False)
    reversed_at = models.DateTimeField(
        "Дата сторно", null=True, blank=True, editable=False
    )
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="Кто сторнировал",
    )
    reversal_reason = models.CharField(
        "Причина сторно", max_length=255, blank=True, editable=False
    )

    class Meta:
        abstract = True

    def mark_reversed(self, user=None, reason=""):
        """Проставить отметки сторно. Сами компенсации делает слой services."""
        self.is_reversed = True
        self.reversed_at = timezone.now()
        # Из бота приходит User, из админки — request.user; аноним отбрасываем.
        self.reversed_by = user if getattr(user, "pk", None) else None
        self.reversal_reason = reason
