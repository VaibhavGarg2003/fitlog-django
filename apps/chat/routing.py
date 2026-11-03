from django.urls import path

from apps.chat.consumers import InboxConsumer

websocket_urlpatterns = [
    path("ws/inbox/", InboxConsumer.as_asgi()),
]
