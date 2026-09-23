#!/usr/bin/env bash
# Точка входа контейнера. Первый аргумент — роль: web | bot | cron.
set -euo pipefail

wait_for_db() {
  echo "[entrypoint] жду базу…"
  for i in $(seq 1 60); do
    if python -c "
import sys, psycopg
from decouple import config
try:
    psycopg.connect(
        dbname=config('DB_NAME'), user=config('DB_USER'),
        password=config('DB_PASSWORD'), host=config('DB_HOST'),
        port=config('DB_PORT', default='5432'), connect_timeout=3,
    ).close()
except Exception:
    sys.exit(1)
" 2>/dev/null; then
      echo "[entrypoint] база готова"
      return 0
    fi
    sleep 2
  done
  echo "[entrypoint] база не поднялась за 2 минуты" >&2
  exit 1
}

case "${1:-web}" in

  web)
    wait_for_db
    # Миграции применяет ТОЛЬКО web — иначе bot и web стартуют одновременно
    # и налетают друг на друга на одной и той же миграции.
    echo "[entrypoint] миграции…"
    python manage.py migrate --noinput
    echo "[entrypoint] статика…"
    python manage.py collectstatic --noinput --clear
    echo "[entrypoint] gunicorn на :8000"
    # 3 воркера с запасом: пользователь один, нагрузка околонулевая.
    # timeout побольше — выгрузка большого Excel-отчёта может быть долгой.
    exec gunicorn config.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers 3 \
        --timeout 120 \
        --access-logfile - \
        --error-logfile -
    ;;

  bot)
    wait_for_db
    # Бот ждёт, пока web накатит миграции: стартовать на старой схеме опаснее,
    # чем подождать.
    echo "[entrypoint] жду миграции (их накатывает web)…"
    for i in $(seq 1 60); do
      if python manage.py migrate --check >/dev/null 2>&1; then break; fi
      sleep 2
    done
    echo "[entrypoint] запускаю бота"
    exec python manage.py runbot
    ;;

  cron)
    wait_for_db
    echo "[entrypoint] планировщик: утренний дайджест"
    exec /app/docker/cron.sh
    ;;

  *)
    # Любая другая команда выполняется как есть: удобно для make-команд
    # (manage.py shell, import_excel и т.п.).
    exec "$@"
    ;;
esac
