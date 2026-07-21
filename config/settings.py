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
AUTHENTICATION_BACKENDS = [
    "apps.users.backends.EmailBackend",
    "django.contrib.auth.backends.ModelBackend"
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Rutas por nombre con namespace, no paths hardcodeados: si la URL se
# mueve, el settings no se entera. DJango las resuelve con reverse()
LOGIN_URL = "users:login"
LOGIN_REDIRECT_URL = "properties:list"
LOGOUT_REDIRECT_URL = "users:login"

# Sesiones - politica V1 (ADR en docs/decisions/auth.md):
# TTL de 2 semana con ventana deslizante. Cada request reescribe la
# sesion y corre el vencimiento: uso frecuente no ve el login nunca;
# inactividad de 2 semanas re-loguea. Costo: un write por request,
# irrelevante a esta escala. Flags en produccion (SESSION_COOKIE_SECURE, 
# CSRF_COOKIE_SECURE) No van aca.
SESSION_COOKIE_AGE = 1209600 # 2 semanas, default explicito
SESSION_SAVE_EVERY_REQUEST = True 



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

# ── Datos de la agencia ─────────────────────────────────────────────
# Consumidos por el comprobante PDF (apps/billing/pdf.py). Van por env
# y NO hardcodeados: el repo es público — CUIT/teléfono/dirección
# reales viven en .env (dev) y en el .env del deploy (prod), mismo
# patrón que R2_*. b9 (V1.1) trae el modelo de configuración de agencia
# (logo); estos campos pueden migrar ahí si el socio necesita editarlos.
AGENCY_NAME    = env.str("AGENCY_NAME", default="Inmobiliaria")
AGENCY_CUIT    = env.str("AGENCY_CUIT", default="")
AGENCY_ADDRESS = env.str("AGENCY_ADDRESS", default="")
AGENCY_PHONE   = env.str("AGENCY_PHONE", default="")
AGENCY_EMAIL   = env.str("AGENCY_EMAIL", default="")


# ── Datos del Geocoding ─────────────────────────────────────────────
# Nominatim (geocoding) — cliente en common/geocoding.py, proxy en properties.
# UA identificable = requisito de la política de uso; el contacto es público.
NOMINATIM_BASE_URL = env.str("NOMINATIM_BASE_URL", default="https://nominatim.openstreetmap.org")
NOMINATIM_USER_AGENT = env.str("NOMINATIM_USER_AGENT", default="Bricka/1.0 (+https://bricka.com.ar)")
NOMINATIM_TIMEOUT = env.float("NOMINATIM_TIMEOUT", default=5.0)
# Geo — centro default del mapa cuando no hay ubicación ni geocoding (§4).
# (lat, lng). Resistencia, Chaco.
GEO_DEFAULT_CENTER = (-27.4512, -58.9866)
GEO_CITY_CENTERS = {
    "Resistencia": (-27.4512, -58.9866),
}


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
