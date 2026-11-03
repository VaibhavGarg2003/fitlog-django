"""
POST /internal/chat/events — the "doorbell" from the Next.js app.

After a chat change COMMITS, Next.js (lib/services/chat-relay.ts) posts an
IDs-only event batch here. We verify it came from Next.js, then push each
event to the recipients' open sockets. Nothing is stored; a lost ring is
fine — clients also catch up over HTTP.

Request:
  headers  x-fitlog-timestamp  unix seconds (±60 s of our clock)
           x-fitlog-event-id   uuid (replays of a recent id are ignored)
           x-fitlog-signature  v1=<hex HMAC-SHA256(CHAT_RELAY_SECRET,
                                       "<timestamp>\n<event id>\n<raw body>")>
  body     {"deliveries": [{"recipients": [uuid, …], "event": {…}}]}

Events are REBUILT from validated fields — never passed through — so this
endpoint can't be used to push arbitrary content to a browser even with a
leaked secret. Not a DRF view: no Supabase JWT here, the HMAC is the auth.
"""

import hashlib
import hmac
import json
import re
import time
from collections import OrderedDict

from channels.layers import get_channel_layer
from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.chat.registry import user_group

MAX_BODY_BYTES = 16 * 1024
MAX_SKEW_SECONDS = 60
MAX_DELIVERIES = 20
MAX_RECIPIENTS = 10
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_MESSAGE_ID = re.compile(r"^[0-9]{1,19}$")
_TIMESTAMP = re.compile(r"^[0-9]{1,12}$")
_SIGNATURE = re.compile(r"^v1=([0-9a-f]{64})$")

_seen_event_ids: "OrderedDict[str, None]" = OrderedDict()
_SEEN_MAX = 2000


def _remember(event_id: str) -> bool:
    """False if this event id was already handled recently."""
    if event_id in _seen_event_ids:
        return False
    _seen_event_ids[event_id] = None
    while len(_seen_event_ids) > _SEEN_MAX:
        _seen_event_ids.popitem(last=False)
    return True


def sign(secret: str, timestamp: str, event_id: str, body: bytes) -> str:
    message = timestamp.encode() + b"\n" + event_id.encode() + b"\n" + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _clean_event(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("type")
    if kind == "message.new":
        cid, mid = raw.get("conversationId"), raw.get("messageId")
        if (
            isinstance(cid, str)
            and _UUID.match(cid)
            and isinstance(mid, str)
            and _MESSAGE_ID.match(mid)
        ):
            return {"type": kind, "conversationId": cid, "messageId": mid}
        return None
    if kind == "conversation.read":
        cid = raw.get("conversationId")
        if isinstance(cid, str) and _UUID.match(cid):
            return {"type": kind, "conversationId": cid}
        return None
    if kind == "buddies.changed":
        return {"type": kind}
    return None


def _deny(status=401):
    return JsonResponse({"error": "rejected"}, status=status)


@csrf_exempt
@require_POST
async def chat_events(request: HttpRequest):
    if not settings.CHAT_LIVE_ENABLED:
        return JsonResponse({"error": "live chat not configured"}, status=503)

    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        return _deny(400)
    if declared > MAX_BODY_BYTES:
        return _deny(413)
    body = request.body
    if len(body) > MAX_BODY_BYTES:
        return _deny(413)

    timestamp = request.headers.get("x-fitlog-timestamp", "")
    event_id = request.headers.get("x-fitlog-event-id", "")
    signature = request.headers.get("x-fitlog-signature", "")
    # ASCII-only, bounded formats: anything else is refused (never a 500).
    sig = _SIGNATURE.fullmatch(signature)
    if not _TIMESTAMP.fullmatch(timestamp) or not _UUID.fullmatch(event_id) or not sig:
        return _deny()
    if abs(time.time() - int(timestamp)) > MAX_SKEW_SECONDS:
        return _deny()
    expected = sign(settings.CHAT_RELAY_SECRET, timestamp, event_id, body)
    if not hmac.compare_digest(expected, sig.group(1)):
        return _deny()

    if not _remember(event_id):
        return JsonResponse({"accepted": 0, "duplicate": True}, status=202)

    try:
        payload = json.loads(body)
    except ValueError:
        return _deny(400)
    deliveries = payload.get("deliveries") if isinstance(payload, dict) else None
    if not isinstance(deliveries, list) or len(deliveries) > MAX_DELIVERIES:
        return _deny(400)

    layer = get_channel_layer()
    accepted = 0
    for delivery in deliveries:
        if not isinstance(delivery, dict):
            continue
        event = _clean_event(delivery.get("event"))
        recipients = delivery.get("recipients")
        if (
            event is None
            or not isinstance(recipients, list)
            or len(recipients) > MAX_RECIPIENTS
        ):
            continue
        for user_id in recipients:
            if isinstance(user_id, str) and _UUID.match(user_id):
                await layer.group_send(
                    user_group(user_id), {"type": "chat.event", "event": event}
                )
                accepted += 1
    return JsonResponse({"accepted": accepted}, status=202)
