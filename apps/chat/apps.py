from django.apps import AppConfig


class ChatConfig(AppConfig):
    """Live chat delivery: the WebSocket "doorbell" for FitLog's chat.

    Messages are stored by the Next.js app in Postgres. This app only tells a
    signed-in user's open tabs that something changed (IDs only), so they
    re-fetch through the authenticated HTTP API.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.chat"
