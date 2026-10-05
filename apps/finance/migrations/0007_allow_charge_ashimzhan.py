"""Разрешить доливать долг Ашимжану.

Банковские кредиты выданы фиксированной суммой — занимать по ним сверх
нельзя. Личный заём, наоборот, периодически растёт, поэтому у него
появляется кнопка «Занять ещё».
"""
from django.db import migrations


def enable(apps, schema_editor):
    apps.get_model("finance", "Obligation").objects.filter(
        code="ashimzhan").update(allow_charge=True)


def disable(apps, schema_editor):
    apps.get_model("finance", "Obligation").objects.filter(
        code="ashimzhan").update(allow_charge=False)


class Migration(migrations.Migration):

    dependencies = [("finance", "0006_obligation_charges")]

    operations = [migrations.RunPython(enable, disable)]
