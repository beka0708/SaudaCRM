"""Страница «Отчёты»: выбор периода и скачивание сводного Excel."""
from datetime import date

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.template.response import TemplateResponse

from apps.analytics.services import month_start, today

from . import services


def _parse(value, default):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


@staff_member_required
def reports_view(request):
    default_start = month_start()
    default_end = today()

    if request.GET.get("download"):
        start = _parse(request.GET.get("start"), default_start)
        end = _parse(request.GET.get("end"), default_end)
        return services.build_period_response(start, end)

    context = admin.site.each_context(request)
    context.update({
        "title": "Отчёты",
        "default_start": request.GET.get("start", default_start.isoformat()),
        "default_end": request.GET.get("end", default_end.isoformat()),
    })
    return TemplateResponse(request, "admin/reports.html", context)
