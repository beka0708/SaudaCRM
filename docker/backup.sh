#!/usr/bin/env sh
# Автоматические бэкапы базы. Запускается как отдельный сервис в цикле.
#
# Данные здесь дороже всего остального: продажи, долги и касса за годы.
# Поэтому дамп не просто делается, а ПРОВЕРЯЕТСЯ — молча испорченный бэкап
# хуже, чем его отсутствие: о проблеме узнаёшь в момент, когда уже поздно.
#
# Схема хранения:
#   daily/   — последние DAILY_KEEP дней (по умолчанию 30)
#   weekly/  — копия за каждое воскресенье, последние WEEKLY_KEEP (12)
#   monthly/ — копия за 1-е число, последние MONTHLY_KEEP (12)
# Так даже порча данных, замеченная через полгода, остаётся откатываемой.
set -eu

DIR="${BACKUP_DIR:-/backups}"
HOUR="${BACKUP_HOUR:-3}"
DAILY_KEEP="${DAILY_KEEP:-30}"
WEEKLY_KEEP="${WEEKLY_KEEP:-12}"
MONTHLY_KEEP="${MONTHLY_KEEP:-12}"
MIN_BYTES="${BACKUP_MIN_BYTES:-20000}"   # дамп меньше — считаем битым

export PGPASSWORD="$DB_PASSWORD"

mkdir -p "$DIR/daily" "$DIR/weekly" "$DIR/monthly"

make_backup() {
  ts=$(date '+%Y-%m-%d_%H%M')
  tmp="$DIR/.tmp_$ts.sql.gz"
  out="$DIR/daily/saudacrm_$ts.sql.gz"

  echo "[backup] $(date '+%F %T') дамп базы $DB_NAME"
  # Пишем во временный файл: если pg_dump оборвётся, в daily/ не появится
  # огрызок, который потом примут за рабочий бэкап.
  if ! pg_dump -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" --no-owner --no-acl \
       | gzip -9 > "$tmp"; then
    echo "[backup] ОШИБКА: pg_dump не отработал" >&2
    rm -f "$tmp"
    return 1
  fi

  size=$(wc -c < "$tmp")
  if [ "$size" -lt "$MIN_BYTES" ]; then
    echo "[backup] ОШИБКА: дамп подозрительно мал ($size байт) — не сохраняю" >&2
    rm -f "$tmp"
    return 1
  fi

  # Проверяем, что архив читается целиком: битый gzip виден сразу.
  if ! gzip -t "$tmp"; then
    echo "[backup] ОШИБКА: архив повреждён" >&2
    rm -f "$tmp"
    return 1
  fi

  mv "$tmp" "$out"
  echo "[backup] готово: $out ($((size / 1024)) КБ)"

  # Воскресенье — недельная копия, 1-е число — месячная.
  [ "$(date +%u)" = "7" ] && cp "$out" "$DIR/weekly/"  || true
  [ "$(date +%d)" = "01" ] && cp "$out" "$DIR/monthly/" || true

  rotate "$DIR/daily"   "$DAILY_KEEP"
  rotate "$DIR/weekly"  "$WEEKLY_KEEP"
  rotate "$DIR/monthly" "$MONTHLY_KEEP"
}

rotate() {
  d="$1"; keep="$2"
  # Считаем, сколько лишних, и удаляем самые старые по имени (в нём дата).
  # Без `head -n -N`: в busybox (alpine) отрицательный аргумент не работает.
  total=$(ls -1 "$d"/saudacrm_*.sql.gz 2>/dev/null | wc -l)
  extra=$((total - keep))
  [ "$extra" -le 0 ] && return 0
  ls -1 "$d"/saudacrm_*.sql.gz 2>/dev/null | sort | head -n "$extra" | while read -r f; do
    echo "[backup] удаляю старый $f"
    rm -f "$f"
  done
}

# Сколько секунд до ближайшего HOUR:00. Считаем арифметикой, а не `date -d`:
# в busybox из alpine GNU-синтаксиса дат нет.
seconds_until() {
  h=$(date +%H); m=$(date +%M); s=$(date +%S)
  now=$((10#$h * 3600 + 10#$m * 60 + 10#$s))
  target=$(( $1 * 3600 ))
  diff=$((target - now))
  [ "$diff" -le 0 ] && diff=$((diff + 86400))
  echo "$diff"
}

# Разовый запуск: docker compose run --rm backup once
if [ "${1:-}" = "once" ]; then
  make_backup
  exit $?
fi

echo "[backup] ежедневно в $(printf '%02d:00' "$HOUR"), хранение $DAILY_KEEP/$WEEKLY_KEEP/$MONTHLY_KEEP"

while true; do
  wait_for=$(seconds_until "$HOUR")
  echo "[backup] следующий дамп через $((wait_for / 3600)) ч $(((wait_for % 3600) / 60)) мин"
  sleep "$wait_for"
  make_backup || echo "[backup] попробую завтра" >&2
done
