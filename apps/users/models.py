from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Сотрудник компании"""

    telegram_id = models.BigIntegerField(
        "Telegram ID", unique=True, null=True, blank=True
    )
    phone = models.CharField("Телефон", max_length=32, blank=True)

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self):
        return self.get_full_name() or self.username
