from pathlib import Path

from decouple import config
from django.urls import reverse_lazy

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", cast=bool)

# На проде — IP сервера (домена нет). Через запятую, если адресов несколько.
ALLOWED_HOSTS = [h.strip() for h in config("ALLOWED_HOSTS", default="*").split(",") if h.strip()]

# Django требует явного списка источников для POST-форм в админке, когда
# обращаются не по localhost. Указывать со схемой и портом: http://1.2.3.4:8000
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in config("CSRF_TRUSTED_ORIGINS", default="").split(",") if o.strip()
]


# Application definition

INSTALLED_APPS = [
    # --- Unfold (должен идти ПЕРЕД django.contrib.admin) ---
    "unfold",
    "unfold.contrib.filters",   # красивые фильтры в списках
    "unfold.contrib.forms",     # виджеты форм (в т.ч. для User)
    "unfold.contrib.inlines",   # улучшенные inline-формы

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # --- Локальные приложения проекта (порядок = порядок зависимостей) ---
    "apps.core",
    "apps.users",
    "apps.clients",
    "apps.catalog",
    "apps.warehouse",
    "apps.sales",
    "apps.debts",
    "apps.finance",
    "apps.reports",
    "apps.analytics",

    # --- Telegram-бот (запуск через manage.py runbot) ---
    "bot",
]

# Кастомная модель пользователя (задана до первых миграций).
AUTH_USER_MODEL = "users.User"

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise отдаёт статику прямо из gunicorn. Без него при DEBUG=False
    # админка Unfold открывается «голой»: runserver статику больше не отдаёт,
    # а отдельный nginx ради одного пользователя ставить незачем.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='saudacrm'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default='127.0.0.1'),
        'PORT': config('DB_PORT', default='5432'),
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'ru-ru'

TIME_ZONE = 'Asia/Bishkek'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Сжимает статику и добавляет хеш в имя файла — браузер не подсунет
    # старый CSS после обновления.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# --- Unfold admin ---
# https://unfoldadmin.com/docs/configuration/settings/
UNFOLD = {
    "SITE_TITLE": "SaudaCRM",
    "SITE_HEADER": "SaudaCRM",
    "SITE_SUBHEADER": "Финансовый учёт и продажи",
    "DASHBOARD_CALLBACK": "apps.analytics.dashboard.dashboard_callback",
    "SITE_DROPDOWN": [],
    "SIDEBAR": {
        "show_search": False,
        "navigation": [
            {
                "title": "Обзор",
                "items": [
                    {"title": "Дашборд", "icon": "dashboard", "link": reverse_lazy("admin:index")},
                    {"title": "Аналитика", "icon": "insights", "link": reverse_lazy("analytics")},
                    {"title": "Отчёты", "icon": "description", "link": reverse_lazy("reports")},
                ],
            },
            {
                "title": "Продажи и склад",
                "items": [
                    {"title": "Продажи", "icon": "receipt_long", "link": reverse_lazy("admin:sales_sale_changelist")},
                    {"title": "Товары", "icon": "inventory_2", "link": reverse_lazy("admin:catalog_product_changelist")},
                    {"title": "Партии / приходы", "icon": "move_to_inbox", "link": reverse_lazy("admin:warehouse_batch_changelist")},
                    {"title": "Списания из партий", "icon": "swap_vert", "link": reverse_lazy("admin:warehouse_batchconsumption_changelist")},
                ],
            },
            {
                "title": "Клиенты и деньги",
                "items": [
                    {"title": "Клиенты", "icon": "groups", "link": reverse_lazy("admin:clients_client_changelist")},
                    {"title": "Реализация (долги)", "icon": "account_balance_wallet", "link": reverse_lazy("admin:debts_debt_changelist")},
                    {"title": "Оплаты долгов", "icon": "payments", "link": reverse_lazy("admin:debts_debtpayment_changelist")},
                    {"title": "Касса", "icon": "account_balance", "link": reverse_lazy("admin:finance_cashflow_changelist")},
                    {"title": "Постоянные расходы", "icon": "event_repeat", "link": reverse_lazy("admin:finance_recurringexpense_changelist")},
                ],
            },
            {
                # Здесь должны МЫ — в отличие от «Реализации», где должны нам.
                "title": "Наши долги",
                "items": [
                    {"title": "Кредиты и займы", "icon": "credit_card", "link": reverse_lazy("admin:finance_obligation_changelist")},
                    {"title": "Движения по долгам", "icon": "sync_alt", "link": reverse_lazy("admin:finance_obligationpayment_changelist")},
                ],
            },
            {
                "title": "Система",
                "items": [
                    {"title": "Пользователи", "icon": "person", "link": reverse_lazy("admin:users_user_changelist")},
                ],
            },
        ],
    },
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "COLORS": {
        "primary": {
            "50": "236 253 245",
            "100": "209 250 229",
            "200": "167 243 208",
            "300": "110 231 183",
            "400": "52 211 153",
            "500": "16 185 129",
            "600": "5 150 105",
            "700": "4 120 87",
            "800": "6 95 70",
            "900": "6 78 59",
            "950": "2 44 34",
        },
    },
    # Боковое меню будем наполнять по мере появления разделов.
    # "SIDEBAR": {"navigation": [...]},
}
