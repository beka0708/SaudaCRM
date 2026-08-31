"""Админка раздела «clients»."""
from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Client


@admin.register(Client)
class ClientAdmin(ModelAdmin):
    list_display = ("name", "phone", "address", "debt_display")
    search_fields = ("name", "phone", "address")

    @admin.display(description="Долг по реализации")
    def debt_display(self, obj):
        return obj.current_debt