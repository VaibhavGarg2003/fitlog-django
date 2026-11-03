from django.urls import path

from apps.chat.relay import chat_events
from apps.chat.views import chat_health

urlpatterns = [
    path("internal/chat/events", chat_events, name="chat-relay"),
    path("api/chat/healthz", chat_health, name="chat-health"),
]
