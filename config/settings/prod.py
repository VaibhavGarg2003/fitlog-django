"""
Production settings — Render.
═════════════════════════════

The "production Django checklist" made concrete:
  DEBUG=False          → never leak stack traces / settings to users
  SECRET_KEY required  → crash at boot if the host didn't set it
                         (a missing secret must be a loud failure, not a
                         silently-insecure fallback)
  ALLOWED_HOSTS        → Host-header attack protection; set per deploy
  HTTPS hardening      → Render terminates TLS at its proxy
"""

from .base import *  # noqa: F403
from .base import env

DEBUG = False

# No fallback — boot fails without it. That's the point.
SECRET_KEY = env("DJANGO_SECRET_KEY")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# Render sits behind a TLS-terminating proxy.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # 30 days; raise once proven stable
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
