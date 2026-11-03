"""
WebSocket admission tickets — verification + single-use consumption.

A ticket is an HS256 JWT minted by the Next.js app (lib/chat/ws-ticket.ts):

    header  {alg: HS256, typ: JWT, kid}
    claims  {iss: "fitlog-web", aud, sub (user uuid), iat, exp = iat + 60, jti}

verify_ticket() checks it strictly (fixed algorithm, known kid, issuer,
audience, required claims, short lifetime, small clock leeway).
consume_ticket() then flips `consumed_at` in ONE conditional UPDATE, so a
ticket admits exactly one connection — even if it was copied, and even
across restarts or an overlapping deploy (an in-memory "used" set could not
promise that).

Key rotation: CHAT_WS_TICKET_PREVIOUS_SECRET/_KID keep the old key valid
while Next.js switches to the new one.
"""

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import jwt
from django.conf import settings

from apps.chat.models import ChatWsTicket

MAX_TICKET_CHARS = 2048
MAX_LIFETIME_SECONDS = 120
LEEWAY_SECONDS = 5
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class TicketError(Exception):
    """The ticket is not acceptable. Never says why to the client."""


@dataclass(frozen=True)
class Ticket:
    user_id: str
    jti: str


def _signing_keys() -> dict[str, str]:
    keys = {}
    if settings.CHAT_WS_TICKET_SECRET:
        keys[settings.CHAT_WS_TICKET_KID] = settings.CHAT_WS_TICKET_SECRET
    if settings.CHAT_WS_TICKET_PREVIOUS_SECRET:
        keys[settings.CHAT_WS_TICKET_PREVIOUS_KID] = (
            settings.CHAT_WS_TICKET_PREVIOUS_SECRET
        )
    return keys


def verify_ticket(token: object) -> Ticket:
    if not isinstance(token, str) or not token or len(token) > MAX_TICKET_CHARS:
        raise TicketError("malformed")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise TicketError("malformed") from exc
    if header.get("alg") != "HS256":
        raise TicketError("algorithm")
    secret = _signing_keys().get(str(header.get("kid")))
    if not secret:
        raise TicketError("unknown key")

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=settings.CHAT_WS_AUDIENCE,
            issuer=settings.CHAT_WS_ISSUER,
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub", "jti", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise TicketError("invalid") from exc

    iat, exp = claims["iat"], claims["exp"]
    if not isinstance(iat, int) or not isinstance(exp, int):
        raise TicketError("invalid times")
    if exp - iat > MAX_LIFETIME_SECONDS or iat > time.time() + LEEWAY_SECONDS:
        raise TicketError("lifetime")
    sub, jti = claims["sub"], claims["jti"]
    if not isinstance(sub, str) or not _UUID.match(sub):
        raise TicketError("subject")
    if not isinstance(jti, str) or not 16 <= len(jti) <= 64:
        raise TicketError("jti")
    return Ticket(user_id=sub, jti=jti)


def consume_ticket(ticket: Ticket) -> bool:
    """Mark the ticket used. True only for the first, unexpired use.

    Synchronous (ORM) — call through channels.db.database_sync_to_async.
    One conditional UPDATE is the whole check: concurrent attempts with the
    same ticket can't both succeed. The row also disappears if the user's
    account is deleted (FK cascade), so a deleted user is refused too.
    """
    now = datetime.now(UTC)
    jti_hash = hashlib.sha256(ticket.jti.encode()).hexdigest()
    updated = ChatWsTicket.objects.filter(
        jti_hash=jti_hash,
        user_id=ticket.user_id,
        consumed_at__isnull=True,
        expires_at__gt=now,
    ).update(consumed_at=now)
    return updated == 1
