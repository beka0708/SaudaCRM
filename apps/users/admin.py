"""Админка раздела «users» (в стиле Unfold)."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from unfold.admin import ModelAdmin
from unfold.forms import (
    AdminPasswordChangeForm,
    UserChangeForm,
    UserCreationForm,
)

from .models import User


@admin.register(User)
class CustomUserAdmin(BaseUserAdmin, ModelAdmin):
    # Формы Unfold — чтобы страницы пользователя выглядели в едином стиле.
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    # Добавляем наши поля в форму редактирования.
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Telegram / контакты",
            {"fields": ("telegram_id", "phone", "receives_notifications")},
        ),
    )
    list_display = (
        "username",
        "get_full_name",
        "telegram_id",
        "receives_notifications",
        "is_staff",
    )
