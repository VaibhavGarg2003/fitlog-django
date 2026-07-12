"""
WSGI entry point — what gunicorn runs in production.

Django doesn't serve itself in production: gunicorn runs N worker
processes of this `application` callable behind the host's proxy.
Defaults to PROD settings — the deployed process must never
accidentally boot with dev settings.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_wsgi_application()
