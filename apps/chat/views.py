"""GET /api/chat/healthz — is live chat up, and how busy is it (counts only)."""

from django.conf import settings
from django.http import JsonResponse

from apps.chat.registry import get_registry


def chat_health(request):
    return JsonResponse(
        {"live": settings.CHAT_LIVE_ENABLED, **get_registry().snapshot()}
    )
