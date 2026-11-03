"""
ASGI entry point — what uvicorn runs in production (one process).

Two kinds of traffic, one process:
  • http       → the normal Django app (share links, admin, health, relay)
  • websocket  → live-chat inbox sockets (apps.chat), Origin-checked

Django is set up BEFORE importing anything that touches models
(get_asgi_application() must run first). Lifespan events are not used —
uvicorn is started with --lifespan off.

Defaults to PROD settings, like wsgi.py: the deployed process must never
boot with dev settings by accident.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import OriginValidator  # noqa: E402
from django.conf import settings  # noqa: E402

from apps.chat.body_limit import RelayBodyLimit  # noqa: E402
from apps.chat.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        # The relay's body limit must apply BEFORE Django buffers the upload.
        "http": RelayBodyLimit(django_asgi_app),
        # A page on any other site can open a WebSocket to us with the
        # visitor's cookies — browsers don't apply CORS to WebSockets. Only
        # our own app's origins may connect (the ticket is the real auth;
        # this stops cross-site pages from even trying).
        "websocket": OriginValidator(
            URLRouter(websocket_urlpatterns),
            settings.CHAT_WS_ALLOWED_ORIGINS,
        ),
    }
)
