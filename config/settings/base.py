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
    "corsheaders",
    "channels",
    # FitLog apps
    "apps.core",
    "apps.sharing",
    "apps.foods",
    "apps.chat",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # CORS must sit high — above CommonMiddleware — so it can answer the
    # browser's preflight OPTIONS before anything else runs.
    "corsheaders.middleware.CorsMiddleware",
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
ASGI_APPLICATION = "config.asgi.application"

# ── Database ────────────────────────────────────────────────────
# DATABASE_URL points at the shared Supabase Postgres (dev project locally,
# prod on Render).
#
# CONN_MAX_AGE = 0: the service now runs under ASGI (uvicorn, for live-chat
# WebSockets). Django's docs say persistent connections should be disabled
# in async mode — they are per-thread, and sync code under ASGI runs on
# changing threads, so kept-alive connections leak instead of being reused.
# Each request opens and closes its connection through the Supabase session
# pooler, which does the pooling.
#
# Falls back to SQLite so the scaffold + unit tests run with no DB secrets.
DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}
if DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
    DATABASES["default"]["CONN_MAX_AGE"] = 0

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
    # Abuse control: link CREATION is the scarce resource (doc 06 hidden
    # requirement 5) — viewing/listing is not throttled here.
    #
    # BEST-EFFORT, not a hard guarantee: DRF's default throttle counts in
    # LocMemCache, which is per-process and non-atomic. A single free-tier
    # instance makes the 20/day effectively hold, but it can be exceeded
    # under a restart, a race, or a future multi-worker/replica deploy. If
    # this ever needs to be a hard cap, point CACHES at the Upstash Redis
    # we already run (shared, atomic INCR) and the same scope applies.
    "DEFAULT_THROTTLE_RATES": {
        "share-create": "20/day",
    },
}

# ── Supabase (JWT verification) ─────────────────────────────────
# The Next.js app and Django trust the SAME identity provider. Django
# verifies Supabase's asymmetric JWT signatures against the project's
# public JWKS — no passwords, no second login, no session sync.
# .strip() defends against a trailing newline/space in a dashboard-set value:
# a stray "\n" makes the JWKS host malformed ("...supabase.co\n"), urllib
# rejects the fetch with InvalidURL, and — since that is NOT a jwt.PyJWTError —
# it escapes the auth handler and 500s every authenticated call. (D5 prod bug.)
SUPABASE_URL = env("SUPABASE_URL", default="").strip()
SUPABASE_JWKS_URL = (
    f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json" if SUPABASE_URL else ""
)
SUPABASE_JWT_AUDIENCE = "authenticated"

# ── CORS ────────────────────────────────────────────────────────
# The Next.js app (a DIFFERENT origin) calls the share-links API from the
# browser, so the exact Vercel origin(s) must be allow-listed. Env-driven
# so the real URL is a deploy-time value, never a code change:
#   CORS_ALLOWED_ORIGINS=https://fitlog.vercel.app,https://preview-….vercel.app
# The PUBLIC GET /api/share-links/<slug> is same-origin (rendered by the
# Next.js server), so CORS mainly matters for create/list/revoke/copy.
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_HEADERS = ["authorization", "content-type"]

# ── Live chat (WebSocket doorbell) ──────────────────────────────
# Next.js stores chat in Postgres; this service only pushes IDs-only hints to
# open browser tabs. Two secrets shared with the Next.js app (never the same
# value): one verifies WebSocket admission tickets, one authenticates relay
# calls. Live chat is OFF unless both are set (≥ 32 characters each).
CHAT_WS_TICKET_SECRET = env("CHAT_WS_TICKET_SECRET", default="").strip()
CHAT_WS_TICKET_KID = env("CHAT_WS_TICKET_KID", default="1").strip()
# During a key rotation, the previous key stays valid for verification.
CHAT_WS_TICKET_PREVIOUS_SECRET = env(
    "CHAT_WS_TICKET_PREVIOUS_SECRET", default=""
).strip()
CHAT_WS_TICKET_PREVIOUS_KID = env(
    "CHAT_WS_TICKET_PREVIOUS_KID", default="0"
).strip()
CHAT_RELAY_SECRET = env("CHAT_RELAY_SECRET", default="").strip()
CHAT_WS_AUDIENCE = env("CHAT_WS_AUDIENCE", default="fitlog-chat-ws").strip()
CHAT_WS_ISSUER = "fitlog-web"
# Browser origins allowed to open the socket (the Next.js app's origins).
CHAT_WS_ALLOWED_ORIGINS = (
    env.list("CHAT_WS_ALLOWED_ORIGINS", default=[]) or CORS_ALLOWED_ORIGINS
)
CHAT_LIVE_ENABLED = (
    len(CHAT_WS_TICKET_SECRET) >= 32
    and len(CHAT_RELAY_SECRET) >= 32
    and CHAT_WS_TICKET_SECRET != CHAT_RELAY_SECRET
)
# Conservative starting caps for a 0.1-CPU free instance; raise after a
# load test.
CHAT_MAX_CONNECTIONS = env.int("CHAT_MAX_CONNECTIONS", default=50)
CHAT_MAX_CONNECTIONS_PER_USER = env.int("CHAT_MAX_CONNECTIONS_PER_USER", default=5)
# Sockets are re-admitted with a fresh ticket this often (bounds how long a
# logged-out or deleted account's socket can linger).
CHAT_LEASE_SECONDS = env.int("CHAT_LEASE_SECONDS", default=600)

# One process ⇒ the in-memory channel layer is enough (and needs no Redis).
# Channels' docs mark it "not for production" because it cannot cross
# processes; with a single process there is nothing to cross. Scaling out
# requires channels_redis. Small per-channel capacity: a slow tab drops
# hints (it catches up over HTTP) instead of buffering without bound.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
        "CONFIG": {"capacity": 50, "expiry": 30},
    }
}

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

# ── Logging ─────────────────────────────────────────────────────
# Django's built-in `django.request` logger routes 500 tracebacks to the
# console handler ONLY under `require_debug_true`. In production (DEBUG=False)
# with no Sentry and no ADMINS, an unhandled view exception would therefore be
# swallowed — the access log shows "500" but the traceback goes nowhere. Send
# it to stdout so the platform (Render) captures it. Applies in every env;
# harmless in dev (dev already prints tracebacks).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "[{levelname}] {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        # ERROR + traceback for any unhandled request exception.
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
