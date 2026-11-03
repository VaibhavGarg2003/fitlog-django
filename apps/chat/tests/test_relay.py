import json
import time
import uuid

import pytest
from asgiref.sync import sync_to_async
from channels.routing import URLRouter
from channels.security.websocket import OriginValidator
from channels.testing import WebsocketCommunicator
from django.test import AsyncClient

from apps.chat import relay
from apps.chat.relay import sign
from apps.chat.routing import websocket_urlpatterns
from apps.chat.tests.conftest import ORIGIN, RELAY_SECRET, make_ticket, store_ticket

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

URL = "/internal/chat/events"


def signed(body: dict, *, secret=RELAY_SECRET, ts=None, event_id=None):
    raw = json.dumps(body).encode()
    ts = str(int(time.time()) if ts is None else ts)
    event_id = event_id or str(uuid.uuid4())
    headers = {
        "x-fitlog-timestamp": ts,
        "x-fitlog-event-id": event_id,
        "x-fitlog-signature": "v1=" + sign(secret, ts, event_id, raw),
    }
    return raw, headers


async def post(raw, headers):
    return await AsyncClient().post(
        URL, data=raw, content_type="application/json", headers=headers
    )


async def listener(user_id):
    token, claims = make_ticket(user_id)
    await sync_to_async(store_ticket)(claims)
    app = OriginValidator(URLRouter(websocket_urlpatterns), [ORIGIN])
    comm = WebsocketCommunicator(
        app, "/ws/inbox/", headers=[(b"origin", ORIGIN.encode())]
    )
    await comm.connect()
    await comm.send_to(text_data=json.dumps({"type": "auth", "ticket": token}))
    assert json.loads(await comm.receive_from())["type"] == "ready"
    return comm


async def test_signed_event_reaches_only_the_recipient():
    alice, bob = str(uuid.uuid4()), str(uuid.uuid4())
    alice_ws, bob_ws = await listener(alice), await listener(bob)
    conv = str(uuid.uuid4())
    raw, headers = signed(
        {
            "deliveries": [
                {
                    "recipients": [alice],
                    "event": {
                        "type": "message.new",
                        "conversationId": conv,
                        "messageId": "42",
                        "body": "SHOULD NOT PASS THROUGH",
                    },
                }
            ]
        }
    )
    res = await post(raw, headers)
    assert res.status_code == 202
    got = json.loads(await alice_ws.receive_from())
    assert got == {
        "type": "event",
        "event": {"type": "message.new", "conversationId": conv, "messageId": "42"},
    }
    assert await bob_ws.receive_nothing(timeout=0.2)
    await alice_ws.disconnect()
    await bob_ws.disconnect()


@pytest.mark.parametrize("tamper", ["secret", "stale", "missing", "body"])
async def test_unauthenticated_relay_calls_are_rejected(tamper):
    body = {
        "deliveries": [
            {"recipients": [str(uuid.uuid4())], "event": {"type": "buddies.changed"}}
        ]
    }
    if tamper == "secret":
        raw, headers = signed(body, secret="w" * 40)
    elif tamper == "stale":
        raw, headers = signed(body, ts=int(time.time()) - 600)
    elif tamper == "missing":
        raw, headers = json.dumps(body).encode(), {}
    else:
        raw, headers = signed(body)
        raw = raw.replace(b"buddies.changed", b"buddies.changeD")
    res = await post(raw, headers)
    assert res.status_code == 401


def _hdrs(ts, sig):
    return {
        "x-fitlog-timestamp": ts,
        "x-fitlog-event-id": str(uuid.uuid4()),
        "x-fitlog-signature": sig,
    }


@pytest.mark.parametrize(
    "headers",
    [
        _hdrs("\u00b2", "v1=" + "a" * 64),  # superscript digit
        _hdrs("9" * 40, "v1=" + "a" * 64),  # absurdly long number
        _hdrs(str(int(time.time())), "v1=" + "\u00e9" * 64),  # non-ASCII
        _hdrs(str(int(time.time())), "v1=abc"),  # wrong length
    ],
)
async def test_malformed_headers_are_rejected_not_500(headers):
    res = await post(b"{}", headers)
    assert res.status_code == 401


async def test_replayed_event_id_is_ignored():
    raw, headers = signed({"deliveries": []})
    assert (await post(raw, headers)).status_code == 202
    res = await post(raw, headers)
    assert res.status_code == 202
    assert res.json().get("duplicate") is True


async def test_bad_events_are_dropped_not_forwarded():
    user = str(uuid.uuid4())
    ws = await listener(user)
    raw, headers = signed(
        {
            "deliveries": [
                {"recipients": [user], "event": {"type": "exec", "code": "alert(1)"}},
                {
                    "recipients": [user],
                    "event": {
                        "type": "message.new",
                        "conversationId": "x",
                        "messageId": "1",
                    },
                },
                {"recipients": ["not-a-uuid"], "event": {"type": "buddies.changed"}},
            ]
        }
    )
    res = await post(raw, headers)
    assert res.status_code == 202
    assert res.json()["accepted"] == 0
    assert await ws.receive_nothing(timeout=0.2)
    await ws.disconnect()


async def test_oversized_body_is_rejected():
    raw, headers = signed({"deliveries": [], "pad": "x" * (relay.MAX_BODY_BYTES + 10)})
    assert (await post(raw, headers)).status_code == 413


async def test_get_is_not_allowed():
    res = await AsyncClient().get(URL)
    assert res.status_code == 405


async def test_disabled_returns_503(settings):
    settings.CHAT_LIVE_ENABLED = False
    raw, headers = signed({"deliveries": []})
    assert (await post(raw, headers)).status_code == 503
