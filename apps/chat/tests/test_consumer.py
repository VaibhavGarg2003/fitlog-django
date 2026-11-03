import asyncio
import json
import uuid

import pytest
from asgiref.sync import sync_to_async
from channels.routing import URLRouter
from channels.security.websocket import OriginValidator
from channels.testing import WebsocketCommunicator

from apps.chat import consumers
from apps.chat.registry import get_registry, reset_registry
from apps.chat.routing import websocket_urlpatterns
from apps.chat.tests.conftest import ORIGIN, make_ticket, store_ticket

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

PING = json.dumps({"type": "ping"})


def app():
    return OriginValidator(URLRouter(websocket_urlpatterns), [ORIGIN])


async def open_socket(origin=ORIGIN):
    comm = WebsocketCommunicator(
        app(), "/ws/inbox/", headers=[(b"origin", origin.encode())]
    )
    connected, code = await comm.connect()
    return comm, connected, code


async def auth_frame(comm, token):
    await comm.send_to(text_data=json.dumps({"type": "auth", "ticket": token}))


async def authed_socket(user_id=None):
    token, claims = make_ticket(user_id)
    await sync_to_async(store_ticket)(claims)
    comm, connected, _ = await open_socket()
    assert connected
    await auth_frame(comm, token)
    ready = json.loads(await comm.receive_from())
    assert ready == {"type": "ready", "leaseSeconds": 600}
    return comm, claims


async def closed_with(comm, code):
    out = await comm.receive_output(timeout=2)
    assert out["type"] == "websocket.close"
    assert out.get("code") == code


async def test_valid_ticket_gets_ready_and_pong():
    comm, _ = await authed_socket()
    await comm.send_to(text_data=PING)
    assert json.loads(await comm.receive_from()) == {"type": "pong"}
    await comm.disconnect()


async def test_wrong_origin_is_rejected():
    _, connected, _ = await open_socket(origin="https://evil.example")
    assert not connected


async def test_reused_ticket_is_refused():
    token, claims = make_ticket()
    await sync_to_async(store_ticket)(claims)
    first, _, _ = await open_socket()
    await auth_frame(first, token)
    assert json.loads(await first.receive_from())["type"] == "ready"

    second, _, _ = await open_socket()
    await auth_frame(second, token)
    await closed_with(second, consumers.CLOSE_TICKET_REFUSED)
    await first.disconnect()


async def test_forged_ticket_is_refused():
    token, claims = make_ticket(secret="f" * 40)
    await sync_to_async(store_ticket)(claims)
    comm, _, _ = await open_socket()
    await auth_frame(comm, token)
    await closed_with(comm, consumers.CLOSE_TICKET_REFUSED)


async def test_first_frame_must_be_auth():
    comm, _, _ = await open_socket()
    await comm.send_to(text_data=PING)
    await closed_with(comm, consumers.CLOSE_TICKET_REFUSED)


async def test_auth_timeout(monkeypatch):
    monkeypatch.setattr(consumers, "AUTH_TIMEOUT_SECONDS", 0.05)
    comm, _, _ = await open_socket()
    await closed_with(comm, consumers.CLOSE_AUTH_TIMEOUT)


async def test_oversized_and_binary_frames_close():
    comm, _ = await authed_socket()
    await comm.send_to(text_data="x" * 5000)
    await closed_with(comm, consumers.CLOSE_BAD_FRAME)

    comm2, _ = await authed_socket()
    await comm2.send_to(bytes_data=bytes([0, 1]))
    await closed_with(comm2, consumers.CLOSE_BAD_FRAME)


async def test_frame_flood_closes():
    comm, _ = await authed_socket()
    # The auth frame already used one slot of the window.
    for _ in range(consumers.MAX_FRAMES_PER_WINDOW - 1):
        await comm.send_to(text_data=PING)
        await comm.receive_from()
    await comm.send_to(text_data=PING)
    await closed_with(comm, consumers.CLOSE_TOO_MANY)


async def test_unknown_frame_after_auth_closes():
    comm, _ = await authed_socket()
    await comm.send_to(text_data=json.dumps({"type": "publish", "to": "someone"}))
    await closed_with(comm, consumers.CLOSE_BAD_FRAME)


async def test_connection_caps(settings):
    settings.CHAT_MAX_CONNECTIONS_PER_USER = 1
    reset_registry()

    user = str(uuid.uuid4())
    first, _ = await authed_socket(user)
    token, claims = make_ticket(user)
    await sync_to_async(store_ticket)(claims)
    second, _, _ = await open_socket()
    await auth_frame(second, token)
    await closed_with(second, consumers.CLOSE_TOO_MANY)
    # A real server reports the close back as websocket.disconnect; the test
    # communicator only does that when told to.
    await second.disconnect()
    await first.disconnect()
    await asyncio.sleep(0.05)
    assert get_registry().snapshot() == {"sockets": 0, "users": 0}


async def test_total_cap_refuses_new_sockets(settings):
    settings.CHAT_MAX_CONNECTIONS = 1
    reset_registry()
    first, connected, _ = await open_socket()
    assert connected
    _, connected2, code = await open_socket()
    assert not connected2
    assert code == consumers.CLOSE_TOO_MANY
    await first.disconnect()


async def test_lease_ends_with_4001(settings):
    settings.CHAT_LEASE_SECONDS = 0.05
    token, claims = make_ticket()
    await sync_to_async(store_ticket)(claims)
    comm, _, _ = await open_socket()
    await auth_frame(comm, token)
    assert json.loads(await comm.receive_from())["type"] == "ready"
    await closed_with(comm, consumers.CLOSE_LEASE_OVER)


async def test_disabled_live_chat_refuses(settings):
    settings.CHAT_LIVE_ENABLED = False
    _, connected, code = await open_socket()
    assert not connected
    assert code == consumers.CLOSE_UNAVAILABLE
