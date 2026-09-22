# Команды SaudaCRM. Всё, что нужно по SSH на сервере.
#   make            — список команд
#   make up         — поднять
#   make logs       — смотреть логи
#   make backup     — снять бэкап прямо сейчас
.DEFAULT_GOAL := help
DC := docker compose
SHELL := /bin/bash

# Подтягиваем .env, иначе команды с psql (make psql, restore, backup-verify)
# получили бы пустые DB_USER/DB_NAME и молча делали не то.
# Дефис — чтобы make не падал, когда .env ещё не создан.
-include .env
export

# Внутри уже запущенного web. Если он лежит — запускаем разовый контейнер.
RUN := $(DC) run --rm web

.PHONY: help
help: ## показать этот список
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------- запуск ----------

.PHONY: up
up: ## собрать и поднять всё
	$(DC) up -d --build
	@echo "Готово. Админка: http://<ip-сервера>:$${WEB_PORT:-8000}/admin/"

.PHONY: down
down: ## остановить (данные и бэкапы остаются)
	$(DC) down

.PHONY: restart
restart: ## перезапустить приложение (без пересборки)
	$(DC) restart web bot cron

.PHONY: ps
ps: ## что сейчас работает
	$(DC) ps

.PHONY: update
update: ## забрать новый код, пересобрать, применить миграции
	git pull
	$(DC) up -d --build
	@echo "Обновлено. Проверь: make logs"

# ---------- логи ----------

.PHONY: logs
logs: ## логи всех сервисов (Ctrl+C — выйти)
	$(DC) logs -f --tail=100

.PHONY: logs-web
logs-web: ## логи веб-сервера
	$(DC) logs -f --tail=100 web

.PHONY: logs-bot
logs-bot: ## логи бота
	$(DC) logs -f --tail=100 bot

.PHONY: logs-backup
logs-backup: ## логи бэкапов
	$(DC) logs -f --tail=50 backup

# ---------- Django ----------

.PHONY: migrate
migrate: ## применить миграции
	$(RUN) python manage.py migrate

.PHONY: superuser
superuser: ## создать администратора
	$(DC) exec web python manage.py createsuperuser

.PHONY: shell
shell: ## Django-шелл
	$(DC) exec web python manage.py shell

.PHONY: bash
bash: ## bash внутри контейнера приложения
	$(DC) exec web bash

.PHONY: psql
psql: ## psql к базе
	$(DC) exec db psql -U $${DB_USER} -d $${DB_NAME}

.PHONY: check
check: ## проверка конфигурации Django
	$(RUN) python manage.py check --deploy

# ---------- дайджест ----------

.PHONY: digest-preview
digest-preview: ## показать дайджест, НЕ отправляя в Telegram
	$(RUN) python manage.py send_digest --dry-run

.PHONY: digest
digest: ## отправить дайджест прямо сейчас
	$(DC) exec cron python manage.py send_digest

# ---------- импорт из Excel (разово, перед запуском) ----------
#
# Порядок: положить файл в папку ./import/ рядом с проектом,
#   make import FILE=таблица.xlsx        — предпросмотр, в базу НИЧЕГО
#   make import-apply FILE=таблица.xlsx  — запись
#   make import-clean                    — убрать файл с сервера
# Импорт рассчитан на ПУСТУЮ базу и делается один раз.

.PHONY: import
import: ## предпросмотр импорта: make import FILE=таблица.xlsx
	@test -n "$(FILE)" || { echo "Укажи файл: make import FILE=таблица.xlsx"; exit 1; }
	@test -f "import/$(FILE)" || { echo "Нет файла import/$(FILE)"; exit 1; }
	$(RUN) python manage.py import_excel "/import/$(FILE)"

.PHONY: import-apply
import-apply: ## ЗАПИСАТЬ импорт: make import-apply FILE=таблица.xlsx
	@test -n "$(FILE)" || { echo "Укажи файл: make import-apply FILE=таблица.xlsx"; exit 1; }
	@test -f "import/$(FILE)" || { echo "Нет файла import/$(FILE)"; exit 1; }
	@echo "Снимаю бэкап перед импортом…"
	@$(MAKE) --no-print-directory backup
	$(RUN) python manage.py import_excel "/import/$(FILE)" --apply

.PHONY: import-clean
import-clean: ## удалить файлы импорта с сервера
	rm -fv import/*.xlsx
	@echo "Папка импорта очищена."

# ---------- бэкапы ----------

.PHONY: backup
backup: ## снять бэкап прямо сейчас
	$(DC) run --rm backup /backup.sh once

.PHONY: backups
backups: ## список бэкапов
	@echo "--- daily ---";   ls -lhtr backups/daily   2>/dev/null | tail -n +2 || echo "  пусто"
	@echo "--- weekly ---";  ls -lhtr backups/weekly  2>/dev/null | tail -n +2 || echo "  пусто"
	@echo "--- monthly ---"; ls -lhtr backups/monthly 2>/dev/null | tail -n +2 || echo "  пусто"

.PHONY: backup-verify
backup-verify: ## проверить, что последний бэкап разворачивается
	@f=$$(ls -1t backups/daily/*.sql.gz 2>/dev/null | head -1); \
	 test -n "$$f" || { echo "Бэкапов нет"; exit 1; }; \
	 echo "Проверяю $$f во ВРЕМЕННОЙ базе (рабочую не трогаю)…"; \
	 $(DC) exec -T db psql -U $${DB_USER} -d postgres -c "DROP DATABASE IF EXISTS verify_tmp;" >/dev/null; \
	 $(DC) exec -T db psql -U $${DB_USER} -d postgres -c "CREATE DATABASE verify_tmp;" >/dev/null; \
	 gunzip -c "$$f" | $(DC) exec -T db psql -q -U $${DB_USER} -d verify_tmp >/dev/null 2>&1; \
	 n=$$($(DC) exec -T db psql -tA -U $${DB_USER} -d verify_tmp -c \
	      "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"); \
	 $(DC) exec -T db psql -U $${DB_USER} -d postgres -c "DROP DATABASE verify_tmp;" >/dev/null; \
	 if [ "$$n" -gt 10 ]; then echo "OK: бэкап разворачивается, таблиц $$n"; \
	 else echo "ПЛОХО: развернулось всего $$n таблиц"; exit 1; fi

.PHONY: restore
restore: ## ВОССТАНОВИТЬ базу: make restore FILE=backups/daily/имя.sql.gz
	@test -n "$(FILE)" || { echo "Укажи файл: make restore FILE=backups/daily/...sql.gz"; exit 1; }
	@test -f "$(FILE)" || { echo "Нет файла $(FILE)"; exit 1; }
	@echo "!!! Текущая база будет ЗАМЕНЕНА на $(FILE)"
	@read -p "Введите БОЛЬШИМИ буквами ВОССТАНОВИТЬ: " a; [ "$$a" = "ВОССТАНОВИТЬ" ] || { echo "Отменено"; exit 1; }
	@echo "Снимаю бэкап текущего состояния на всякий случай…"
	@$(MAKE) --no-print-directory backup
	$(DC) stop web bot cron
	$(DC) exec -T db psql -U $${DB_USER} -d postgres -c "DROP DATABASE IF EXISTS $${DB_NAME};"
	$(DC) exec -T db psql -U $${DB_USER} -d postgres -c "CREATE DATABASE $${DB_NAME} LOCALE 'C' TEMPLATE template0;"
	gunzip -c "$(FILE)" | $(DC) exec -T db psql -q -U $${DB_USER} -d $${DB_NAME}
	$(DC) start web bot cron
	@echo "Восстановлено из $(FILE)"
