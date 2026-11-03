import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from apps.chat.registry import reset_registry

TICKET_SECRET = "t" * 40
RELAY_SECRET = "r" * 40
ORIGIN = "https://app.example"


@pytest.fixture(autouse=True)
def live_settings(settings):
    settings.CHAT_WS_TICKET_SECRET = TICKET_SECRET
    settings.CHAT_WS_TICKET_KID = "1"
    settings.CHAT_WS_TICKET_PREVIOUS_SECRET = ""
    settings.CHAT_RELAY_SECRET = RELAY_SECRET
    settings.CHAT_WS_AUDIENCE = "fitlog-chat-ws"
    settings.CHAT_WS_ALLOWED_ORIGINS = [ORIGIN]
    settings.CHAT_LIVE_ENABLED = True
    settings.CHAT_MAX_CONNECTIONS = 50
    settings.CHAT_MAX_CONNECTIONS_PER_USER = 5
    settings.CHAT_LEASE_SECONDS = 600
    reset_registry()
    yield
    reset_registry()


def make_ticket(
    user_id=None,
    *,
    secret=TICKET_SECRET,
    kid="1",
    aud="fitlog-chat-ws",
    iss="fitlog-web",
    iat=None,
    ttl=60,
    jti=None,
    alg="HS256",
):
    iat = int(time.time()) if iat is None else iat
    claims = {
        "iss": iss,
        "aud": aud,
        "sub": user_id or str(uuid.uuid4()),
        "iat": iat,
        "exp": iat + ttl,
        "jti": jti or uuid.uuid4().hex,
    }
    token = jwt.encode(claims, secret, algorithm=alg, headers={"kid": kid})
    return token, claims


def store_ticket(claims, *, expires_in=60, consumed=False):
    """Insert the ticket row Next.js would have written (sha256 of jti)."""
    import hashlib

    from apps.chat.models import ChatWsTicket

    now = datetime.now(UTC)
    ChatWsTicket.objects.create(
        jti_hash=hashlib.sha256(claims["jti"].encode()).hexdigest(),
        user_id=claims["sub"],
        expires_at=now + timedelta(seconds=expires_in),
        consumed_at=now if consumed else None,
        created_at=now,
    )
