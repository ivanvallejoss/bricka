import environ
import sentry_sdk
from pathlib import Path
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.celery import CeleryIntegration
from django.contrib.messages import constants as message_constants

# environ setup
env = environ.Env()
BASE_DIR = Path(__file__).resolve().parent.parent
environ.Env.read_env(BASE_DIR / ".env")

# ENVIRONMENT VARIABLES
SECRET_KEY = env.str("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "django_htmx",
    # Internal
    "apps.common",
    "apps.users",
    "apps.properties",
    "apps.listings",
    "apps.contacts",
    "apps.deals",
    "apps.documents",
    "apps.contracts",
    "apps.billing",
    "apps.integrations",
    "apps.portal",
    "apps.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.BackofficeLoginRequiredMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database
DATABASES = {"default": env.db("DATABASE_URL")}

# Redis
REDIS_URL = env.str("REDIS_URL", default="redis://localhost:6379/0")

# Cache
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# Celery
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TIMEZONE = "America/Argentina/Buenos_Aires"
CELERY_TASK_TRACK_STARTED = True

# Auth
AUTH_USER_MODEL = "users.User"
LOGIN_URL = "/backoffice/login/"
LOGIN_REDIRECT_URL = "/backoffice/"

# --------------------------------------------------------------------------
# Storage de Django (framework). NADA de la media de negocio pasa por acá:
# fotos de propiedades, documentos legales y logo van por common/storage.py
# (boto3 directo → R2). Este bloque existe solo para staticfiles (CSS/JS).
# No hay FileField/ImageField en el dominio.
# --------------------------------------------------------------------------
if DEBUG:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    MEDIA_URL = "/media/"
    MEDIA_ROOT = BASE_DIR / "media"
    R2_PUBLIC_BASE_URL = env.str("R2_PUBLIC_BASE_URL", default="")
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }

# --------------------------------------------------------------------------
# Cloudflare R2 — media de negocio (boto3 directo, S3-compatible).
# Idéntico en dev y prod: misma ruta de código, buckets distintos por entorno.
# El aislamiento de datos lo da el .env (dev → buckets *-dev; prod → reales).
# Sin defaults: si falta una variable, debe explotar al arrancar, no degradar
# a string vacío que produce URLs rotas en runtime.
# --------------------------------------------------------------------------
R2_ACCOUNT_ID            = env.str("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID         = env.str("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY     = env.str("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT_URL          = env.str("R2_ENDPOINT_URL")           # https://<account>.r2.cloudflarestorage.com
R2_PUBLIC_MEDIA_BUCKET   = env.str("R2_PUBLIC_MEDIA_BUCKET")    # bricka-media-dev / bricka-media
R2_PRIVATE_DOCS_BUCKET   = env.str("R2_PRIVATE_DOCS_BUCKET")    # bricka-documents-dev / bricka-documents
R2_PUBLIC_MEDIA_BASE_URL = env.str("R2_PUBLIC_MEDIA_BASE_URL")

# Static
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# Django messages — remapea el nivel ERROR al tag `danger`
# para alinear con los tokens semánticos FRD (danger-bg / danger-text).
# Evita crear tokens error-* que colisionarían con la familia Material existente.
MESSAGE_TAGS = {
    message_constants.ERROR: "danger",
}

# Internacionalización
LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_I18N = True
USE_TZ = True

# Fallback sobre PKs
# para las tablas generales del sistema se utiliza UUIDv4
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Sentry — se activa solo si SENTRY_DSN está presente en el entorno
SENTRY_DSN = env.str("SENTRY_DSN", default="")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )
