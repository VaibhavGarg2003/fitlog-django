"""
Development settings — the laptop.
DEBUG on, throwaway secret key, permissive hosts. NEVER deployed.
"""

from .base import *  # noqa: F403

DEBUG = True

# Throwaway — fine for dev, useless anywhere else.
SECRET_KEY = SECRET_KEY or "dev-only-insecure-key-do-not-deploy"  # noqa: F405

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Dev convenience: plain static storage (no manifest hashing on reload),
# and whitenoise serving straight from app dirs — no collectstatic needed,
# and no "No directory at staticfiles/" warning.
STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
WHITENOISE_AUTOREFRESH = True
WHITENOISE_USE_FINDERS = True
