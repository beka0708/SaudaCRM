"""Утренний дайджест в Telegram — пять отдельных сообщений.

Собирается из готовых метрик `analytics.services` (арифметики здесь нет) и
уходит через `core.notifications.broadcast` — всем сотрудникам с галочкой
«Получает уведомления» и заполненным Telegram ID.

Блоки:
  1. Выручка и себестоимость за день  4. Показатели по месяцам
  2. Личные расходы за месяц          5. Остатки на складе
  3. Должники

Отдельными сообщениями, а не одним полотном: так список должников/остатков
не упрётся в лимит Telegram в 4096 символов.

ВАЖНО про даты:
  - блок 1 — за ВЧЕРА (дайджест уходит в 9:00, за сегодня продаж ещё нет);
  - блоки 2 и 4 — за календарный месяц, см. `_month_range`.

Текст уходит с parse_mode=HTML, поэтому всё, что ввёл человек (названия
товаров, имена клиентов), пропускаем через html.escape — иначе имя с «&»
или «<» сломает отправку сообщения целиком.
"""
from datetime import timedelta
from html import escape

from apps.analytics import services as A

_MONTHS = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)
_WEEKDAYS = (
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
)


def _month_name(d) -> str:
    return f"{_MONTHS[d.month - 1]} {d.year}"


def _date_label(d) -> str:
    return f"{d:%d.%m.%Y}, {_WEEKDAYS[d.weekday()]}"


def _month_last_day(d):
    """Последнее число месяца, к которому относится `d` (учитывает февраль)."""
    first = d.replace(day=1)
    return (first + timedelta(days=31)).replace(day=1) - timedelta(days=1)


def _month_range(day):
    """Календарный месяц, к которому относится `day`: с 1-го числа по СЕГОДНЯ,
    но не дальше конца этого месяца.

    Почему не просто «по day»: в середине месяца сводка должна включать и то,
    что внесли СЕГОДНЯ, иначе только что вбитый расход в неё не попадёт.

    Почему не просто «по сегодня»: 1-го числа `day` — последний день прошлого
    месяца, и надо показать ЗАКРЫВШИЙСЯ месяц целиком, а не пустой новый.
    """
    start = day.replace(day=1)
    return start, min(_month_last_day(start), A.today())


def _pct(part, whole) -> str:
    return f" ({part / whole * 100:.0f}%)" if whole else ""


# --- блоки ---

def _block_revenue(day) -> str:
    rc = A.revenue_and_cogs(day, day)
    revenue, cogs = rc["revenue"], rc["cogs"]
    head = f"💵 <b>SaudaCRM — выручка за {_date_label(day)}</b>"
    if not revenue:
        return f"{head}\n\nПродаж не было."
    profit = revenue - cogs
    return (
        f"{head}\n\n"
        f"Продажи: {A.money(revenue)} сом\n"
        f"Себестоимость: {A.money(cogs)} сом\n"
        f"Прибыль: <b>{A.money(profit)} сом</b>{_pct(profit, revenue)}"
    )


def _block_personal(day) -> str:
    from apps.finance.models import CashFlow

    start, end = _month_range(day)
    total = A.expenses_by_category(CashFlow.Category.PERSONAL, start, end)
    head = f"💳 <b>Личные расходы — {_month_name(day)}</b>"
    if not total:
        return f"{head}\n\nРасходов пока не было."
    return f"{head}\n\nВсего с начала месяца: <b>{A.money(total)} сом</b>"


def _block_debtors() -> str:
    rows, total = A.all_debtors()
    if not rows:
        return "📋 <b>Должники</b>\n\nДолжников нет."
    lines = [f"{escape(r['name'])} — {A.money(r['debt'])}" for r in rows]
    return (
        f"📋 <b>Должники — {len(rows)}</b>\n\n"
        + "\n".join(lines)
        + f"\n\nИтого должны: <b>{A.money(total)} сом</b>"
    )


def _block_indicators(day) -> str:
    cur_start, cur_end = _month_range(day)
    prev_start, prev_end = A.prev_month_range(day)

    def part(title, start, end, note=""):
        m = A.month_indicators(start, end)
        return (
            f"<b>{title}</b>{note}\n"
            f"Выручка: {A.money(m['revenue'])} сом\n"
            f"Себестоимость: {A.money(m['cogs'])} сом\n"
            f"Расходы: {A.money(m['expenses'])} сом\n"
            f"Чистая прибыль: <b>{A.money(m['profit'])} сом</b>"
            f"{_pct(m['profit'], m['revenue'])}"
        )

    # Текущий месяц первым — он интереснее. Если он ещё не закрыт, помечаем
    # «по DD.MM»: иначе неполный месяц легко сравнить с полным прошлым и
    # решить, что дела пошли хуже.
    note = "" if cur_end >= _month_last_day(cur_start) else f" (по {cur_end:%d.%m})"
    return (
        "📈 <b>Показатели по месяцам</b>\n\n"
        + part(_month_name(cur_start).capitalize(), cur_start, cur_end, note)
        + "\n\n"
        + part(_month_name(prev_start).capitalize(), prev_start, prev_end)
    )


def _block_stock() -> str:
    rows, total = A.stock_report()
    if not rows:
        return "📦 <b>Остатки на складе</b>\n\nСклад пуст."
    lines = [
        f"{escape(r['name'])} — {r['packs']} {r['pack_label']} · {A.money(r['value'])} сом"
        for r in rows
    ]
    return (
        f"📦 <b>Остатки на складе — {len(rows)} товаров</b>\n\n"
        + "\n".join(lines)
        + f"\n\nИтого по себестоимости: <b>{A.money(total)} сом</b>"
    )


# --- сборка и отправка ---

def build_blocks(day=None) -> list[str]:
    """Пять блоков дайджеста, каждый — отдельное сообщение."""
    if day is None:
        day = A.today() - timedelta(days=1)
    return [
        _block_revenue(day),
        _block_personal(day),
        _block_debtors(),
        _block_indicators(day),
        _block_stock(),
    ]


def build_digest(day=None) -> str:
    """Весь дайджест одним текстом — для предпросмотра в консоли (--dry-run)."""
    return "\n\n".join(build_blocks(day))


def send_digest(day=None) -> int:
    """Разослать дайджест пятью сообщениями. Возвращает число успешных отправок."""
    from apps.core.notifications import broadcast

    return sum(broadcast(block) for block in build_blocks(day))
