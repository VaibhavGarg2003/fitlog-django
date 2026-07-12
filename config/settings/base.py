"""
Base settings — shared by every environment.
═════════════════════════════════════════════

The settings SPLIT (base / dev / prod) is the Django version of FitLog's
env-vars lesson: the same code must behave differently per environment,
and the differences must be explicit files, not scattered if-statements.

    manage.py  → config.settings.dev   (laptop default)
    wsgi.py    → config.settings.prod  (gunicorn/Render default)

Secrets come from the environment (django-environ reads .env locally;
Render injects real env vars in production). Nothing secret lives here.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
# Read .env if present (local dev). In production there is no .env file —
# the host's environment variables are the source of truth.
environ.Env.read_env(BASE_DIR / ".env")

# SECURITY: no default on purpose — every environment must set it.
# dev.py provides a throwaway; prod REQUIRES a real one from the host env.
SECRET_KEY = env("DJANGO_SECRET_KEY", default=None)

DEBUG = False  # environments opt IN to debug, never out of it

ALLOWED_HOSTS: list[str] = []

# ── Apps ────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    # FitLog apps
    "apps.core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ── Database ────────────────────────────────────────────────────
# DATABASE_URL points at the shared Supabase Postgres (dev project locally,
# prod on Render). Django is a long-running SERVER, so unlike the Next.js
# serverless functions it can hold persistent connections — CONN_MAX_AGE
# keeps them alive between requests (the thing serverless couldn't do).
#
# Falls back to SQLite so the scaffold + unit tests run with no DB secrets.
DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}
if DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
    DATABASES["default"]["CONN_MAX_AGE"] = 60

# ── DRF ─────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    # Deny-by-default: every endpoint requires auth unless it explicitly
    # opts out (same posture as the Next.js API routes).
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # Supabase JWT verification lives in apps.core (added in D2).
        "apps.core.authentication.SupabaseJWTAuthentication",
    ],
    "UNAUTHENTICATED_USER": None,
}

# ── Supabase (JWT verification) ─────────────────────────────────
# The Next.js app and Django trust the SAME identity provider. Django
# verifies Supabase's asymmetric JWT signatures against the project's
# public JWKS — no passwords, no second login, no session sync.
SUPABASE_URL = env("SUPABASE_URL", default="")
SUPABASE_JWKS_URL = (
    f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json" if SUPABASE_URL else ""
)
SUPABASE_JWT_AUDIENCE = "authenticated"

# ── Auth / i18n / static ────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"  # store UTC; user-local dates come FROM the client
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
