#!/usr/bin/env bash
# Простейший планировщик для одной задачи в сутки — утреннего дайджеста.
#
# Почему не Celery: одна рассылка в день на бюджетном сервере не стоит
# брокера, воркера и beat. Почему не системный cron: контейнер тогда
# зависел бы от настройки хоста, а так он самодостаточен и переживает
# перезагрузку сервера сам (restart: unless-stopped).
set -euo pipefail

HOUR="${DIGEST_HOUR:-9}"     # час отправки, локальное время контейнера
MINUTE="${DIGEST_MINUTE:-0}"

echo "[cron] дайджест ежедневно в $(printf '%02d:%02d' "$HOUR" "$MINUTE") ($(date +%Z))"

# Секунды до ближайшего HOUR:MINUTE — арифметикой, без GNU-синтаксиса `date -d`,
# чтобы скрипт вёл себя одинаково в любом базовом образе.
seconds_until() {
  h=$(date +%H); m=$(date +%M); s=$(date +%S)
  now=$((10#$h * 3600 + 10#$m * 60 + 10#$s))
  target=$(( $1 * 3600 + $2 * 60 ))
  diff=$((target - now))
  [ "$diff" -le 0 ] && diff=$((diff + 86400))
  echo "$diff"
}

while true; do
  sleep_for=$(seconds_until "$HOUR" "$MINUTE")
  echo "[cron] следующая отправка через $((sleep_for / 60)) мин"
  sleep "$sleep_for"

  echo "[cron] $(date '+%F %T') отправляю дайджест"
  # Сбой рассылки не должен ронять планировщик — иначе одна сетевая
  # ошибка выключит дайджест навсегда.
  python manage.py send_digest || echo "[cron] ОШИБКА отправки, пробую завтра" >&2
done
