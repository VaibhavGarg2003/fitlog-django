"""
InboxConsumer — one per open browser tab (ws path: /ws/inbox/).

Protocol (mirrors Next.js lib/chat/live-protocol.ts):

  client → { "type": "auth", "ticket": "<jwt>" }   first frame, within 5 s
  server → { "type": "ready", "leaseSeconds": 600 }
  client → { "type": "ping" }                       every 25 s
  server → { "type": "pong" }
  server → { "type": "event", "event": {...} }      IDs-only hint (relay.py)

Close codes: 4001 lease over (client reconnects with a fresh ticket),
4400 bad frame, 4401 ticket refused, 4408 auth timeout, 4429 too many
connections or frames, 4503 live chat not configured.

Nothing the client sends can reach another user: the group is derived only
from the verified ticket's subject, and the only accepted frames after auth
are pings. The client never publishes through this socket — chat writes go
through the Next.js HTTP API.
"""

import asyncio
import json
import logging
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

from apps.chat.registry import get_registry, user_group
from apps.chat.tickets import TicketError, consume_ticket, verify_ticket

log = logging.getLogger(__name__)

AUTH_TIMEOUT_SECONDS = 5
MAX_FRAME_CHARS = 4096
FRAME_WINDOW_SECONDS = 10
MAX_FRAMES_PER_WINDOW = 20

CLOSE_LEASE_OVER = 4001
CLOSE_BAD_FRAME = 4400
CLOSE_TICKET_REFUSED = 4401
CLOSE_AUTH_TIMEOUT = 4408
CLOSE_TOO_MANY = 4429
CLOSE_UNAVAILABLE = 4503


class InboxConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user_id = None
        self.counted = False
        self.user_counted = False
        self.timers: list[asyncio.Task] = []
        self.frames: list[float] = []

        if not settings.CHAT_LIVE_ENABLED:
            await self.close(code=CLOSE_UNAVAILABLE)
            return
        if not get_registry().try_open():
            await self.close(code=CLOSE_TOO_MANY)
            return
        self.counted = True
        await self.accept()
        self.timers.append(
            asyncio.create_task(
                self._close_after(
                    AUTH_TIMEOUT_SECONDS,
                    CLOSE_AUTH_TIMEOUT,
                    only_if_unauthenticated=True,
                )
            )
        )

    async def disconnect(self, code):
        for task in self.timers:
            task.cancel()
        registry = get_registry()
        if self.user_id:
            await self.channel_layer.group_discard(
                user_group(self.user_id), self.channel_name
            )
            if self.user_counted:
                registry.remove_user(self.user_id)
        if self.counted:
            registry.close()
            self.counted = False

    async def receive(self, text_data=None, bytes_data=None):
        if (
            bytes_data is not None
            or text_data is None
            or len(text_data) > MAX_FRAME_CHARS
        ):
            await self.close(code=CLOSE_BAD_FRAME)
            return
        if not self._within_frame_budget():
            await self.close(code=CLOSE_TOO_MANY)
            return
        try:
            frame = json.loads(text_data)
        except ValueError:
            await self.close(code=CLOSE_BAD_FRAME)
            return
        kind = frame.get("type") if isinstance(frame, dict) else None

        if self.user_id is None:
            if kind != "auth":
                await self.close(code=CLOSE_TICKET_REFUSED)
                return
            await self._authenticate(frame.get("ticket"))
            return

        if kind == "ping":
            await self.send(text_data='{"type":"pong"}')
            return
        await self.close(code=CLOSE_BAD_FRAME)

    async def chat_event(self, message):
        """Group message from the relay → this socket."""
        await self.send(
            text_data=json.dumps({"type": "event", "event": message["event"]})
        )

    # ── internals ────────────────────────────────────────────────

    async def _authenticate(self, token):
        try:
            ticket = verify_ticket(token)
        except TicketError:
            await self.close(code=CLOSE_TICKET_REFUSED)
            return
        try:
            consumed = await database_sync_to_async(consume_ticket)(ticket)
        except Exception:  # noqa: BLE001 — DB down: refuse, client backs off
            log.exception("ticket consumption failed")
            consumed = False
        if not consumed:
            await self.close(code=CLOSE_TICKET_REFUSED)
            return
        if not get_registry().try_add_user(ticket.user_id):
            await self.close(code=CLOSE_TOO_MANY)
            return

        self.user_id = ticket.user_id
        self.user_counted = True
        await self.channel_layer.group_add(
            user_group(ticket.user_id), self.channel_name
        )
        lease = settings.CHAT_LEASE_SECONDS
        await self.send(text_data=json.dumps({"type": "ready", "leaseSeconds": lease}))
        self.timers.append(
            asyncio.create_task(self._close_after(lease, CLOSE_LEASE_OVER))
        )

    async def _close_after(self, seconds, code, only_if_unauthenticated=False):
        await asyncio.sleep(seconds)
        if only_if_unauthenticated and self.user_id is not None:
            return
        await self.close(code=code)

    def _within_frame_budget(self) -> bool:
        now = time.monotonic()
        self.frames = [t for t in self.frames if now - t < FRAME_WINDOW_SECONDS]
        self.frames.append(now)
        return len(self.frames) <= MAX_FRAMES_PER_WINDOW
